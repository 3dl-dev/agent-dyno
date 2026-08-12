# Agent Dyno

You've built a real system for coding with AI — a way of wiring up models,
subagents, review, and effort that gets work done. Agent Dyno helps you see what
your setup already does well, and find the next bit of leverage, using your own
data, on your own machine, with your numbers staying yours.

And it does one more thing: it helps everyone get better together. The moment
someone's setup finds a real unlock, the technique behind it becomes something
the rest of us can try on the next run. You bring your wins to the commons, and
you take home everyone else's.

## How it helps

A dynamometer measures an engine's real output under load. Agent Dyno does the
same for a coding setup: it reads your logs and your git history and shows how
efficiently your **harness** turns tokens into work that **survives** — code that
ships and stays shipped.

- It starts from what's working. Every setup has real strengths; the report leads
  with yours.
- It surfaces opportunities from your own numbers, never from a rulebook. You
  decide what to try; you watch your own number move.
- It learns from everyone. The improvements it suggests are validated wins mined
  from real setups like yours — with the evidence — not best-practice lectures.

Nothing is prescribed by fiat. Nothing is uploaded unless you choose to share it.

## What it measures

- **Fuel** is tokens (priced in dollars, since input/output/cache differ ~20×).
- **The engine** is your harness: model routing, delegation, review regime, effort.
- **Work** is what survives in git — not reverted, not rebuilt, not later
  bug-fixed. Measured at a horizon, so durable work is what counts, and the tool
  is honest about the difference between output and output that lasts.

Efficiency is a **vector**, never a single score — the best setup on one axis is
rarely best on another, so you see the whole picture and pick what matters to you.

## Your numbers are yours

You measure your **own** engine, for your **own** improvement. The shared
leaderboard is about engine *craft* — which techniques turn tokens into durable
work — never about ranking people, and never tied to product outcomes (whether a
feature wins the market is a bet nobody controls). Contributions are opt-in and
anonymized: the *technique and the numbers* travel; your identity, your repos,
and your code never do. See [docs/governance.md](docs/governance.md).

## Get better together

The frontier is a living commons of validated leverage. Each contribution carries
the transferable part — the engine configuration that produced a result, plus the
result — so that when your `dyno-tune` says "setups like yours that tried this saw
that," it's pointing at something real that someone actually did, and you can
adopt it in an afternoon. Someone 10x's a workflow; next run, that pattern is
waiting for the rest of us. See [frontier/](frontier/).

## Quickstart

```bash
# The objective numerator — works on any repo, any agent, no setup:
python3 core/survival_git.py --repo /path/to/your/repo --since 30.days.ago

# A full, friendly efficiency report from your Claude Code logs:
#   hand skills/dyno-report to your agent — it runs locally, stdlib only.
```

## Harness-agnostic by design

The measure of surviving work is a **git** property, so it's the same for a human,
Claude Code, pi, or OpenCode — everyone deposits into the same history. Only the
token side is harness-specific, and it lives behind a thin **adapter** (Claude
Code built; pi and opencode are open slots). Models plug in through a price
registry. So whatever you run, you're welcome, and your wins count.

## What's here

- `core/` — the harness-neutral git-survival numerator + per-engine attribution.
- `adapters/` — per-harness token extraction (claude-code built; pi, opencode slots).
- `skills/` — self-contained agent skills (report, dynamometer, tune).
- `frontier/` — the opt-in, community-maintained commons of technique.
- `leaderboard/` — the public leaderboard of engine craft.
- `docs/` — the method, the governance, the claims register.

## Status

Early and honest. The harness-neutral numerator and per-engine attribution are
built and dogfooded; day/week horizon curves and the pi/opencode adapters grow as
data and contributors arrive. The [claims register](docs/claims.md) tracks what's
measured, confirmed, and still open. Come help — every setup you bring makes the
commons better for the next person.

## License

MIT. Use it, fork it, own your own numbers, share your wins.
