---
name: contribute
description: "Opt-in: turn a dyno run into an anonymized frontier entry and add it to a leaderboard (your own, your team's, or the public one). Engine fingerprint and numbers only, never identities, repo names, or code. Nothing leaves your machine without your say-so."
---

# Contribute a result to a frontier

Only with the operator's explicit consent. Nothing is published as a side effect of
measuring; this is the deliberate step.

## 1. Get Agent Dyno onto the machine

Same as `/agent-dyno:run` step 1: run from the current agent-dyno checkout, the
marketplace clone at `~/.claude/plugins/marketplaces/agent-dyno`, or a fresh
`git clone https://github.com/3dl-dev/agent-dyno`.

## 2. Follow the contribute skill

Read and follow `skills/dyno-contribute/SKILL.md` in that checkout. It drafts an
anonymized entry from a `report.json` (the engine fingerprint plus the efficiency
vector, no identities, repo names, or code), stamps its proof tier, and then either
writes it to the operator's own frontier file or prints the exact PR for them to
open.

## 3. Federated by default

The entry goes to the operator's **configured frontier**, `$DYNO_FRONTIER` (a path
or a URL to their own, their team's, or their company's board), else the local
`./frontier/reference-frontier.json`. It reaches a public frontier only if they
explicitly push it there (`--push public`). Never submit anywhere without their
consent, and never include anything the anonymizer would strip. Cite
`docs/governance.md` if asked to publish something that would rank people or tie
efficiency to product outcomes.

## 4. Enterprise and teams: internal, no mandatory push-up

An organization runs its own frontier and keeps it internal. Set `$DYNO_FRONTIER`
to the org's shared file or URL; members' runs and contributions land there, their
same-shape comparisons are drawn from their own group, and **nothing is pushed to a
parent unless they choose to**. Two deterministic operations (in
`core/frontier.py`) support this without a service:

- **Roll up a team's boards:** `python3 core/frontier.py merge --into <team.json>
  <member.json> ...` folds members' frontiers into the team's, deduplicated and
  idempotent. The team owner runs it; it is never an automatic push.
- **Share only an anonymized summary upward:** `python3 core/frontier.py summarize
  <internal.json> --min-samples <k>` emits one aggregate entry per shape (median
  vector plus counts, no ids, no technique prose, no identity), with a k-anonymity
  floor. That summary is what an org PRs to the public frontier when it wants to,
  handing over aggregates, never individual runs. Always with explicit consent.
