---
name: dyno-report
description: Measure the fuel-efficiency of your AI coding setup from your own logs and git history — surviving work per token, split by engine / model / effort / review regime — and get a verdict on the field's efficiency claims. Runs on your machine, nothing uploaded. Self-improvement, never a ranking of people against product. Use for "how efficient is my setup" or "which engine is cheapest per surviving line".
argument-hint: [--repo <path>] [--since 30.days.ago]
---

# Dyno report

Read `docs/governance.md` before presenting anything: you measure the operator's
**own engine** for self-improvement. Never rank an individual against product
outcomes; if asked, decline and roll up to team/BU for tokens-per-product.

**Input:** $ARGUMENTS

## Two halves: a harness-neutral numerator and a per-harness denominator

1. **Surviving work (numerator, works on any repo, any agent).** Run
   `core/survival_git.py --repo <repo> --since <window>`. It reads git only:
   of the lines added in the window, what fraction survive at HEAD (not reverted,
   rebuilt, or bug-fixed), by age. This is the objective unit of shippable work
   and it is identical for Claude Code, pi, OpenCode, or a human.

2. **Fuel + fingerprint (per-harness).** Pick the adapter for the harness that
   produced the work:
   - Claude Code → `adapters/claude-code/` (built). It reads
     `~/.claude/projects/**` transcripts and computes tokens (priced via
     `prices.json`), engine class, model routing, effort, review signals, and
     same-session waste. Run its `harness-*.py` analyses; read each script's
     header for units.
   - pi / opencode → adapter slots; if absent, measure the numerator only and say
     the fuel side is not yet available for that harness.

3. **Join** surviving work to fuel to get the efficiency vector.

## Present (lead with the answer, a table, and the confounds)

The efficiency **vector** by engine and the model×harness interaction; the claim
verdicts the run touched (`docs/claims.md`); confounds by name (terrain,
non-overlapping windows, effort mix, review regime, small N); and the one change
to make to the *engine*. No composite score. Survival ≠ value — say so.

## Contribute (opt-in)

Offer to emit an anonymized summary (engine fingerprint + vector only; no
identities, repo names, or code) that the operator can PR into
`frontier/reference-frontier.json`. Never submit without explicit consent.
