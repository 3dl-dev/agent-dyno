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

The entry goes to the operator's **own** frontier (local file, team repo, or
company location) and reaches a public one only if they explicitly push it there
(`--push public`). Never submit anywhere without their consent, and never include
anything the anonymizer would strip. Cite `docs/governance.md` if asked to publish
something that would rank people or tie efficiency to product outcomes.
