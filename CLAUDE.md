# CLAUDE.md: developing and curating Agent Dyno

Instructions for an agent working ON this repo (not just using the tool). For
using the tool to measure a setup, read `AGENTS.md`. For getting started as a
user, read `docs/getting-started.md`.

## What this repo is

Agent Dyno measures the token-efficiency of an AI coding setup: surviving work per
token, harness-neutral, self-owned, federated. The philosophy is in
`docs/governance.md` and `docs/protocol.md`. Read them before changing anything;
they are load-bearing, not decoration.

## Rules for editing this repo

- **Preserve the invariant.** Never add a feature that ranks individuals against
  product outcomes, or that measures value instead of survival. `docs/governance.md`
  is the constitution. Plumbing changes are welcome; philosophy changes are not,
  absent an explicit decision.
- **Source first, code second.** A `.py` is a reference build, not the source. A
  tool lands as a spec (`<tool>.spec.md`) plus an acceptance test
  (`test_<tool>.py`) first; the code follows and must pass the test. Behavior
  changes are spec-and-test changes. See `SOURCE.md`.
- **Stdlib only.** Python 3 standard library, no installs, no new dependencies. If
  a change seems to need a dependency, it is the wrong change.
- **No em-dashes.** Anywhere: docs, comments, commit messages. Use commas, colons,
  periods, semicolons. Verify with `grep -rn '—'` before committing.
- **The four-slot schema.** Every new dimension lands in exactly one existing slot:
  a fingerprint axis, a fuel line, a horizon on the numerator, or a claim row. A
  dimension that needs a fifth slot is a signal to stop and rethink.
- **Keep it simple.** Adoption is the whole value. A change that adds setup
  friction for a user is suspect no matter how clever.

## Curating the public frontier

Contributions arrive as pull requests against `frontier/reference-frontier.json`.
The curator agent's job is to keep the board honest, in proportion to the claim:

1. **Tier 0, always:** reject entries that fail sanity (survival outside [0,100],
   non-positive tokens, impossible ratios). Check that the entry is anonymized: no
   identities, repo names, code, or product data. Rewrite or reject if not.
2. **Tier 2, git-verifiable:** if the entry cites a public repo and SHAs, re-run
   `core/survival_git.py` against it and confirm the surviving-work number.
3. **Tier 3, reproduced:** a claim that would top the public frontier must be
   reproduced. Re-run the stated engine configuration on a standard task with the
   dynamometer (`adapters/claude-code/run-engine.py` and `skills/dyno-dynamometer`)
   and confirm the number holds before merging. Do not take a top claim on trust.
4. **Merge or comment.** Merge confirmed entries with their proof tier recorded.
   For the rest, comment with what would raise the tier. Reproduction cost is the
   sybil tax; low-effort floods sit behind verified, cost-bearing submissions.

The public frontier lives here at `3dl-dev/agent-dyno`. It is one frontier among
many; teams run their own (see `docs/federation.md`). Curation applies only to what
this repo publishes.

## Where things are

- `core/`: the harness-neutral numerator and per-engine attribution, with spec and test.
- `adapters/`: per-harness fuel extraction (claude-code built; pi, opencode slots).
- `skills/`: the self-contained agent skills (report, tune, dynamometer, contribute).
- `frontier/`: the JSON commons and its schema.
- `leaderboard/`: the static leaderboard page.
- `docs/`: governance, protocol, federation, SOURCE, claims, getting-started.
