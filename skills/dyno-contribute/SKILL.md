---
name: dyno-contribute
description: Turn a dyno run into a leaderboard entry and add it to a frontier. Federated by default: your entry goes to your own frontier (local, team, or company), and only reaches a public one if you explicitly push it up. Drafts an anonymized entry, stamps its proof tier, and either writes it to your frontier file or prints the exact PR for you to open. No signup, no keys, no dependency.
argument-hint: [--frontier <path-or-url>] [--push public|team] [--repo <public-repo-for-tier-2>]
---

# Dyno contribute

Read `docs/federation.md` and `docs/governance.md`. A frontier is just a
`reference-frontier.json` file someone hosts. This skill adds an entry to one.
Federated by default: it writes to the operator's own frontier and never reaches a
parent unless told to. Nothing is shared without an explicit push.

**Input:** $ARGUMENTS

## Steps

1. **Take a run.** Use the latest `dyno-report` result (efficiency vector,
   fingerprint, engine, effort, review regime, survival horizon, sample size). If
   there isn't one, run `dyno-report` first.

2. **Draft the entry, anonymized.** Build the JSON object for the frontier schema
   (`frontier/reference-frontier.json`, `agent-dyno/frontier@2`): the transferable
   **technique** (the engine configuration that produced the result, described so
   someone else can adopt it), the **fingerprint**, the **vector**, the
   **horizon**, the **samples**, and a **date**. Include **nothing** that
   identifies the operator: no name, no repo names, no code, no product data. If
   any of those would leak through the technique text, rewrite it generically.

3. **Stamp the proof tier** (`docs/federation.md`):
   - **Tier 0** first, always: reject if survival is outside [0,100], tokens are
     not positive, or a ratio is physically impossible. Fix or refuse.
   - **Tier 2** if the run was over a *public* repo: include the repo URL and the
     commit SHAs so anyone can re-run `core/survival_git.py` and confirm.
   - **Tier 3** only after a dynamometer reproduction confirmed the number; do not
     self-assign it.
   - Otherwise **Tier 1**, self-report. Never claim a higher tier than the evidence.

4. **Write it to the target frontier.**
   - **Default (federated, your scope):** append the entry to the frontier file at
     `--frontier` (default `./frontier/reference-frontier.json`). This is your
     team's or your own board. Done. Nothing left your control.
   - **Push up (`--push`):** only on explicit request. For a team frontier, write
     or PR against that frontier's file. For `public`, print the exact `git`/PR
     steps to open a pull request against `3dl-dev/agent-dyno`, curated by Third
     Division Labs. Show the operator the entry and get a yes before doing it.

5. **Render, optionally.** Point `leaderboard/dyno.html` at the frontier file, or
   POST the formatted standings to a Slack or Discord incoming webhook if the
   operator gives one. A frontier is plain JSON; any surface works.

## Rules

- Federated by default. Local write needs no permission; any push to a parent
  needs explicit consent.
- Anonymized always: technique and numbers travel, identity and code never do.
- Honest tiers: a topped public board requires Tier 3 reproduction, not a claim.
- No dependency: files, a GitHub PR, and an optional webhook. Nothing to install.
