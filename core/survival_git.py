#!/usr/bin/env python3
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--since", default="90.days.ago")
    args = ap.parse_args()

    now = time.time()
    commits = window_commits(args.repo, args.since)
    if not commits:
        print("no commits in window", file=sys.stderr)
        return
    # scope blame to files still present at HEAD that were touched in the window
    tracked = set(git(args.repo, "ls-files").splitlines())
    paths = {p for c in commits.values() for p in c["paths"]} & tracked
    surviving = surviving_by_commit(args.repo, paths)

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
    print("=" * 64)
    print(f"HORIZON-SURVIVAL  repo={args.repo}  window since {args.since}")
    print(f"commits={len(commits)}  lines added={total_added:,}  "
          f"surviving at HEAD={total_surv:,}  ({100*total_surv/max(1,total_added):.1f}%)")
    print(f"\n{'code age when added':22}{'added':>10}{'surviving%':>13}")
    print("-" * 45)
    for i, lbl in enumerate(labels):
        added, surv = agg[i]
        if added:
            print(f"{lbl:22}{added:>10,}{100*surv/added:>12.1f}%")
    print(f"\nfix/revert commits added {fix_added:,} lines "
          f"({100*fix_added/max(1,total_added):.1f}% of churn is rework/defect-driven)")
    print("\nsurviving% = lines still blamed to the adding commit at HEAD. "
          "Falling values at older ages = code that didn't last.")


if __name__ == "__main__":
    main()
