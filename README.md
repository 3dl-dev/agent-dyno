# Agent Dyno

Measure the fuel-efficiency of your AI coding setup — how many tokens it takes to
produce work that **survives** — and compare notes with everyone else, before
someone who controls the purse imposes a metrics regime that measures the wrong
thing.

A dynamometer measures an engine's real output under load. Agent Dyno does the
same for a coding agent: it runs on your own logs and your own git history, and
reports how efficiently your **harness** (how you wire the models, subagents,
review, and effort) turns tokens into code that lasts.

## Why this exists

The token-cost backlash keeps asking the wrong question: *are you building value
with the tokens?* Value is not attributable. You cannot trace an engineer's
tokens to a product feature that wins the market — that is a bet, unpredictable
in advance, no more forecastable than whether a program halts. Measuring people
against product outcomes imports noise nobody controls, and it turns
self-reporting into surveillance.

So Agent Dyno measures something objective instead: **surviving work per token.**

- **Fuel** is tokens (priced in dollars, since input/output/cache differ ~20×).
- **The engine** is your harness: model routing, delegation topology, review
  regime, reasoning effort.
- **Work** is what *survives* in git — code not reverted, not rebuilt, not later
  bug-fixed. Measured at a horizon (a day, a week), so a harness that skips
  review can't fake it: unverified code dies, and its numerator collapses.

## The one rule

**An individual measures tokens-per-surviving-output, for self-improvement. A
team or company measures tokens-per-product. Nobody ranks an individual against
product outcomes.** If every engine is fuel-efficient, the unit ships efficiently
— with no product-linked personal KPI required. Ranking individuals on product is
a misuse of this tool, not a use of it. The reporting is built so that misuse is
hard: individual data is self-owned and opt-in; the shared leaderboard compares
*engine craft*, never people-against-features. See [docs/governance.md](docs/governance.md).

## Harness-agnostic by design

The numerator is a **git measurement**, so it is neutral across every agent and
model. Which lines added at time T are still alive at T+N is a property of the
repository, not of the tool that typed them. A human, Claude Code, pi, or
OpenCode all deposit into the same git history and are measured the same way.

Only the token/cost/fingerprint side is harness-specific, and it lives behind a
thin **adapter**. Claude Code is the first adapter; `pi` and `opencode` are
adapter slots, not rewrites. Models plug in through a price registry, never
hardcoded.

## Quickstart

```bash
# 1. Objective numerator, works on any repo, any agent:
python3 core/survival_git.py --repo /path/to/your/repo --since 30.days.ago

# 2. Full efficiency report from Claude Code logs (the first adapter):
#    see skills/dyno-report — hand it to your agent, it runs locally, stdlib only.
```

Nothing is uploaded. Everything runs on your machine. Contributing your
(anonymized, opt-in) numbers to the shared frontier is a pull request you choose
to make — see [frontier/](frontier/).

## What ships here

The factory, the operator, and the code, as one unit — nothing held in reserve:

- `core/` — the harness-neutral git-survival numerator.
- `adapters/` — per-harness extraction into a common schema (claude-code built; pi, opencode as slots).
- `skills/` — self-contained agent skills (report, dynamometer, tune); the method lives in the SKILL.md, so any agent runs them cold.
- `frontier/` — the opt-in, community-maintained reference numbers.
- `leaderboard/` — the public leaderboard page.
- `docs/` — the protocol, the governance invariant, the claims register.

## Status

Early and honest. The concept and the harness-neutral numerator are built and
dogfooded; horizon-survival attribution (mapping surviving lines to the harness
that wrote them) and the pi/opencode adapters are in progress. The
[claims register](docs/claims.md) tracks what is measured, what is confirmed, and
what is still open — including the review-methodology debates, which are just
more rows.

## License

MIT. Use it, fork it, own your own numbers.
