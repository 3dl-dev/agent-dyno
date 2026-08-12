# spec: survival_git

The harness-neutral numerator. Measures how much added code survives, from git
alone, so it is identical for any agent, model, or human.

## Interface

```
survival_git --repo <path> [--since <git-approxidate>]
```

Reads only the git repository. No network, no transcript, no state outside the
repo and the system clock.

## Method

1. **Window commits.** `git log --since=<since> --no-merges` over the repo. For
   each commit record: its commit time, its subject, and from `--numstat` the
   number of lines added and the set of paths it touched. Ignore binary numstat
   rows (shown as `-`).
2. **Surviving lines.** Restrict to paths still tracked at HEAD that a window
   commit touched. For each such path, `git blame HEAD --line-porcelain` and count,
   per commit sha, how many lines at HEAD are still attributed to it. A line that
   was deleted or rewritten is no longer attributed to the adding commit, so it
   does not count as surviving. This is the definition of survival.
3. **Per-commit survival.** `survival(commit) = surviving_lines / added_lines`.
4. **Age buckets.** Bucket each commit by its age in days at run time, using
   boundaries `[<1, 1-3, 3-7, 7-14, 14-30, 30-90, >90]`. Report, per non-empty
   bucket, the total lines added and the aggregate survival percentage
   (sum surviving / sum added within the bucket).
5. **Churn proxy.** Report the share of added lines that came from commits whose
   subject matches `fix|bug|revert|regression|hotfix|patch` (case-insensitive), as
   a crude rework/defect signal.
6. **Totals.** Report window commit count, total lines added, total surviving, and
   overall survival percentage.

## Determinism

Output is a pure function of (repo state at HEAD, commit history in the window,
current date). Same repo and same day gives the same numbers.

## Known limits (must be stated in output or docs, not hidden)

- `git blame` is line-exact: a cosmetic reformat resets blame and undercounts
  survival.
- The churn proxy is commit-message-based, not true defect attribution.
- Repo-level only; attributing survival to a session or harness is a separate tool
  (`horizon_attribute`).

## Acceptance

`test_survival_git.py` builds a throwaway repo, adds N lines in one commit, deletes
K of them in a later commit, and asserts the tool reports `(N-K)/N` overall
survival. A build that does not pass this is not a valid build.
