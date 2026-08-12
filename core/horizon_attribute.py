#!/usr/bin/env python3
"""
horizon_attribute.py, join surviving git lines to the engine that wrote them.

This is what turns the harness-neutral numerator into a per-engine long-horizon
comparison. survival_git.py answers "did the code last"; this answers "did *this
engine's* code last", by mapping each commit to the session that produced it and
carrying that session's engine / model / effort fingerprint.

Mapping is by time + project: a commit in repo R at time T is attributed to the
session whose project matches R and whose active window contains T (commits
usually land at or just after a session's end, so a short tail tolerance is
allowed). Fuzzy but adapter-neutral; a harness that stamps a session id into its
commit trailer can override this with an exact join later.

Inputs:
  --repo      a git repo
  --snapshot  a retained snapshot dir (from adapters/<harness>/snapshot.py):
              its mb-*.jsonl session+turn records supply engine/time/fuel.
Stdlib + git only.

Result: per engine, of the lines it added in the window, what fraction survive at
HEAD, the real horizon-survival numerator, attributed.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import time
from collections import defaultdict
from datetime import datetime

SHA_RE = re.compile(r"^([0-9a-f]{40}) ")


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True,
                          text=True, errors="replace").stdout


def parse_iso(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def engine_of(sess):
    if (sess.get("workflows") or 0) > 0 or (sess.get("wf_agents") or 0) > 0:
        return "workflow"
    if (sess.get("plain_agents") or 0) > 0:
        return "delegate"
    return "solo"


def load_sessions(snapshot, repo_name):
    """From snapshot mb records: sessions whose project matches this repo,
    with [start,end] window, engine, dominant model+effort."""
    sess = {}
    turns = defaultdict(list)
    for p in glob.glob(os.path.join(snapshot, "mb-*.jsonl")) + \
            glob.glob(os.path.join(snapshot, "*", "mb-*.jsonl")):
        for line in open(p):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("k") == "session":
                sess[r["sess"]] = r
            elif r.get("k") == "turn":
                turns[r["sess"]].append(r)
    out = []
    for sid, s in sess.items():
        proj = (s.get("proj") or "")
        if repo_name not in proj:
            continue
        ts = sorted(parse_iso(t["ts"]) for t in turns.get(sid, []) if t.get("ts"))
        ts = [t for t in ts if t]
        if not ts:
            continue
        efforts = [t.get("effort") for t in turns.get(sid, []) if t.get("effort")]
        out.append({
            "sid": sid, "start": ts[0], "end": ts[-1],
            "engine": engine_of(s),
            "model": (s.get("model") or "?").split("[")[0].replace("claude-", ""),
            "effort": max(set(efforts), key=efforts.count) if efforts else "unknown",
        })
    return out


def commit_survival(repo, since):
    """Per commit: (ts, added, surviving_at_HEAD)."""
    out = git(repo, "log", f"--since={since}", "--no-merges",
              "--pretty=format:C|%H|%ct", "--numstat")
    commits, cur = {}, None
    for line in out.splitlines():
        if line.startswith("C|"):
            _, sha, ct = line.split("|", 2)
            cur = sha
            commits[sha] = {"ts": int(ct), "added": 0, "paths": set()}
        elif line.strip() and cur:
            parts = line.split("\t")
            if len(parts) == 3 and parts[0] != "-":
                commits[cur]["added"] += int(parts[0])
                commits[cur]["paths"].add(parts[2])
    tracked = set(git(repo, "ls-files").splitlines())
    paths = {p for c in commits.values() for p in c["paths"]} & tracked
    surviving = defaultdict(int)
    for path in paths:
        for line in git(repo, "blame", "HEAD", "--line-porcelain", "--", path).splitlines():
            m = SHA_RE.match(line)
            if m:
                surviving[m.group(1)] += 1
    for sha, c in commits.items():
        c["surviving"] = surviving.get(sha, 0)
    return commits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--since", default="45.days.ago")
    ap.add_argument("--tail", type=float, default=900, help="seconds after session end a commit may still attribute (default 900)")
    args = ap.parse_args()

    repo_name = os.path.basename(os.path.abspath(args.repo).rstrip("/"))
    sessions = load_sessions(args.snapshot, repo_name)
    commits = commit_survival(args.repo, args.since)
    if not sessions:
        print(f"no sessions in snapshot match project '{repo_name}'")
        return

    agg = defaultdict(lambda: [0, 0, 0])  # key -> [added, surviving, n_commits]
    matched = unmatched = 0
    for sha, c in commits.items():
        if c["added"] == 0:
            continue
        cand = [s for s in sessions if s["start"] - args.tail <= c["ts"] <= s["end"] + args.tail]
        if not cand:
            unmatched += 1
            continue
        s = min(cand, key=lambda s: abs((s["start"] + s["end"]) / 2 - c["ts"]))
        matched += 1
        key = (s["engine"], s["effort"])
        agg[key][0] += c["added"]
        agg[key][1] += c["surviving"]
        agg[key][2] += 1

    print("=" * 60)
    print(f"HORIZON-SURVIVAL BY ENGINE  repo={repo_name}  since {args.since}")
    print(f"commits matched to a session: {matched}  unmatched: {unmatched}")
    print(f"\n{'engine / effort':22}{'commits':>9}{'added':>10}{'surviving%':>13}")
    print("-" * 54)
    for key in sorted(agg, key=lambda k: -agg[k][0]):
        added, surv, n = agg[key]
        print(f"{key[0]+' / '+key[1]:22}{n:>9}{added:>10,}{100*surv/max(1,added):>12.1f}%")
    print("\nsurviving% = this engine's added lines still alive at HEAD. As "
          "retained snapshots accrue, the same join yields day/week horizon curves.")


if __name__ == "__main__":
    main()
