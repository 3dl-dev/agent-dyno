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
import datetime
import json
import re
import subprocess
import sys
import time
from collections import defaultdict

SHA_RE = re.compile(r"^([0-9a-f]{40}) ")
FIXY = re.compile(r"\b(fix|bug|revert|regression|hotfix|patch)\b", re.I)
_SINCE_RE = re.compile(r"(\d+)\.(day|week|month)s?\.ago")


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


def _since_to_date(since, now):
    """Convert a git approxidate like '30.days.ago' to YYYY-MM-DD for a forge
    query. Returns None if the form is not one we can convert."""
    m = _SINCE_RE.match(since or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    days = n * {"day": 1, "week": 7, "month": 30}[unit]
    d = datetime.datetime.utcfromtimestamp(now) - datetime.timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def changes(repo, since, now=None):
    """DORA change throughput + change failure rate, harness-neutral.

    A 'change' is a merged pull request (the accepted unit of shipped work), NOT
    a commit (an arbitrary checkpoint). Source, in order: the forge (merged PRs
    via `gh`, the faithful unit) -> git trunk integrations (first-parent history,
    a labeled approximation that degrades to commits when work lands straight on
    the trunk). change_failure_rate = share of changes that are fixes/reverts, the
    standard cheap proxy for DORA's 'changes that required remediation'.
    """
    now = time.time() if now is None else now
    date = _since_to_date(since, now)
    # 1. forge: merged PRs (the accepted unit) via gh, best-effort
    if date and "github.com" in git(repo, "remote", "get-url", "origin"):
        try:
            out = subprocess.run(
                ["gh", "pr", "list", "--state", "merged", "--limit", "1000",
                 "--search", f"merged:>={date}", "--json", "title"],
                cwd=repo, capture_output=True, text=True, timeout=30, check=True).stdout
            prs = json.loads(out)
            total = len(prs)
            failed = sum(1 for p in prs if FIXY.search(p.get("title", "")))
            return {"source": "github-pr", "changes": total, "failed": failed,
                    "change_failure_rate": round(100 * failed / total, 2) if total else None}
        except Exception:
            pass
    # 2. fallback: git trunk integrations (first-parent), labeled approximate
    out = git(repo, "log", f"--since={since}", "--first-parent",
              "--pretty=format:%s")
    subs = [s for s in out.splitlines() if s.strip()]
    total = len(subs)
    failed = sum(1 for s in subs if FIXY.search(s))
    return {"source": "git-trunk (approx)", "changes": total, "failed": failed,
            "change_failure_rate": round(100 * failed / total, 2) if total else None}


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
    return {
        "repo": repo,
        "since": since,
        "commits": len(commits),
        "added": total_added,
        "surviving": total_surv,
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
    ch = changes(args.repo, args.since)
    print(f"changes (DORA, {ch['source']})={ch['changes']}  "
          f"change failure rate={ch['change_failure_rate']}%")
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
