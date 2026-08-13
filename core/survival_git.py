#!/usr/bin/env python3
# REFERENCE BUILD. Source of truth: survival_git.spec.md (what it must do)
# + test_survival_git.py (the verification). Code is a regenerable artifact:
# rebuild it from the spec and the acceptance test must still pass. See SOURCE.md.
"""
harness-survival-git.py, horizon-survival, measured from git (harness-neutral).

The objective numerator of the Harness Efficiency Protocol: of the lines added in
a past window, what fraction are still alive at HEAD (survived), and what fraction
were later touched by a fix/revert (defect signal). This is a property of the
repository, not of the agent that typed the code, so it works identically for
Claude Code, pi, OpenCode, or a human, across any model family. Git is the shared
substrate.

Method (one blame pass, scoped to touched files):
  1. `git log --since` → window commits, their added-line counts, touched paths.
  2. blame HEAD on those paths → surviving lines attributed to each window commit.
  3. survival(commit) = surviving_lines / added_lines; bucket by commit age.
  4. defect signal: later commits whose subject matches fix/bug/revert that modify
     lines a window commit had added (approximated: fix-commits in the repo since).

Usage:
  python3 harness-survival-git.py [--repo .] [--since 90.days] [--author-map runs.jsonl]
No deps beyond git + Python stdlib.
"""
import argparse
import re
import subprocess
import sys
import time
from collections import defaultdict

SHA_RE = re.compile(r"^([0-9a-f]{40}) ")
FIXY = re.compile(r"\b(fix|bug|revert|regression|hotfix|patch)\b", re.I)


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True, errors="replace").stdout


def window_commits(repo, since):
    """Return {sha: {added, ts, subj, paths:set}} for commits in the window."""
    out = git(repo, "log", f"--since={since}", "--no-merges",
              "--pretty=format:C|%H|%ct|%s", "--numstat")
    commits = {}
    cur = None
    for line in out.splitlines():
        if line.startswith("C|"):
            _, sha, ts, subj = line.split("|", 3)
            cur = sha
            commits[sha] = {"added": 0, "ts": int(ts), "subj": subj, "paths": set()}
        elif line.strip() and cur:
            parts = line.split("\t")
            if len(parts) == 3:
                added, _deleted, path = parts
                if added != "-":
                    commits[cur]["added"] += int(added)
                    commits[cur]["paths"].add(path)
    return commits


def surviving_by_commit(repo, paths):
    """One blame pass over `paths`; return {sha: surviving_line_count}."""
    surviving = defaultdict(int)
    for path in paths:
        out = git(repo, "blame", "HEAD", "--line-porcelain", "--", path)
        if not out:
            continue
        for line in out.splitlines():
            m = SHA_RE.match(line)
            if m:
                surviving[m.group(1)] += 1
    return surviving


def survival(repo, since, now=None):
    """Compute horizon-survival for `repo` over the window `since`.

    Returns a structured dict (or None if the window is empty). This is the
    importable numerator other tools (e.g. the dyno_report driver) consume, so
    they need not scrape stdout. main() renders this same dict. Totals
    (added / surviving / pct / fix-share) are clock-independent; only the age
    buckets depend on `now`, so callers that want deterministic output can pass a
    fixed `now` or ignore the buckets.
    """
    now = time.time() if now is None else now
    commits = window_commits(repo, since)
    if not commits:
        return None
    # scope blame to files still present at HEAD that were touched in the window
    tracked = set(git(repo, "ls-files").splitlines())
    paths = {p for c in commits.values() for p in c["paths"]} & tracked
    surviving = surviving_by_commit(repo, paths)

    # per-commit survival, bucketed by age
    buckets = [(0, 1), (1, 3), (3, 7), (7, 14), (14, 30), (30, 90), (90, 10**6)]
    labels = ["<1d", "1-3d", "3-7d", "7-14d", "14-30d", "30-90d", ">90d"]
    agg = defaultdict(lambda: [0, 0])  # bucket -> [added, surviving]
    fix_added = 0
    for sha, c in commits.items():
        if c["added"] == 0:
            continue
        if FIXY.search(c["subj"]):
            fix_added += c["added"]
        age_d = (now - c["ts"]) / 86400
        surv = surviving.get(sha, 0)
        for i, (lo, hi) in enumerate(buckets):
            if lo <= age_d < hi:
                agg[i][0] += c["added"]
                agg[i][1] += surv
                break

    total_added = sum(c["added"] for c in commits.values())
    total_surv = sum(surviving.get(s, 0) for s in commits)
    # Attempts: a commit is one discrete swing at value (a login button and a
    # neural net can each be one). Scope-agnostic on purpose: weighting by size
    # would smuggle back the value-prediction the method rejects. A surviving
    # attempt is one whose work is still alive at HEAD (not reverted or rebuilt).
    attempts = sum(1 for c in commits.values() if c["added"] > 0)
    surviving_attempts = sum(1 for sha, c in commits.items()
                             if c["added"] > 0 and surviving.get(sha, 0) > 0)
    return {
        "repo": repo,
        "since": since,
        "commits": len(commits),
        "added": total_added,
        "surviving": total_surv,
        "attempts": attempts,
        "surviving_attempts": surviving_attempts,
        "pct": 100 * total_surv / max(1, total_added),
        "buckets": [(labels[i], agg[i][0], agg[i][1]) for i in range(len(labels))],
        "fix_added": fix_added,
        "fix_pct": 100 * fix_added / max(1, total_added),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--since", default="90.days.ago")
    args = ap.parse_args()

    r = survival(args.repo, args.since)
    if r is None:
        print("no commits in window", file=sys.stderr)
        return
    print("=" * 64)
    print(f"HORIZON-SURVIVAL  repo={args.repo}  window since {args.since}")
    print(f"commits={r['commits']}  lines added={r['added']:,}  "
          f"surviving at HEAD={r['surviving']:,}  ({r['pct']:.1f}%)")
    print(f"attempts (commits w/ code)={r['attempts']}  "
          f"surviving attempts={r['surviving_attempts']}  "
          f"({100*r['surviving_attempts']/max(1,r['attempts']):.1f}%)")
    print(f"\n{'code age when added':22}{'added':>10}{'surviving%':>13}")
    print("-" * 45)
    for lbl, added, surv in r["buckets"]:
        if added:
            print(f"{lbl:22}{added:>10,}{100*surv/added:>12.1f}%")
    print(f"\nfix/revert commits added {r['fix_added']:,} lines "
          f"({r['fix_pct']:.1f}% of churn is rework/defect-driven)")
    print("\nsurviving% = lines still blamed to the adding commit at HEAD. "
          "Falling values at older ages = code that didn't last.")


if __name__ == "__main__":
    main()
