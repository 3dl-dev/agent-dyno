# Vibrant

Vibrant measures how efficiently your AI coding setup turns tokens into work
that lasts. It reads your own logs and your git history, on your machine, and gives
you one number, your worst bottleneck, and the single change most likely to move
it. Nothing leaves your machine unless you choose to share it.

## Use it

In Claude Code, add the marketplace and install the plugin:

```
/plugin marketplace add 3dl-dev/vibrant
/plugin install vibrant@vibrant
```

Then measure your setup:

```
/vibrant:run
```

It reads your local Claude Code logs and your git history for the repos you code in,
and writes three files: `report.md`, `report.html`, and `report.json`. On first use
it fetches Vibrant onto your machine and checks the install; after that it just
measures. It runs on the Python standard library, with no other install and no keys.
Nothing is uploaded.

When you want to share a result, `/vibrant:contribute` drafts an anonymized entry
(engine fingerprint and numbers only, no code or identities) and adds it to a
frontier you choose, or prints the pull request for you to open. Publishing is
always a separate, deliberate step.

## What you get

`report.md` is the whole surface. It opens with one number:

```
# Your setup: 382.35 functionality per Mtok output

Larger is better. Surviving decision-logic (a complexity proxy) per million tokens
the model generated, over 4 sessions. Change failure rate 50.0% (DORA).
```

Under the number sits your biggest lever: the single change most likely to raise
it, taken from setups shaped like yours on the shared frontier, with the gain it is
predicted to buy. The frontier is young, so when nothing shaped like your setup
beats you yet, the report says so plainly instead of inventing a suggestion. Change
your setup, run it again, and the report shows whether the number moved as
predicted.

`report.html` is a self-contained page with two charts. The first is your
efficiency over time, with the changes you made to your own setup flagged on the
curve, so a move ties to something you did and not to noise. The second is your
fuel and your work over time, which you can slice by model, effort, engine, or
review regime. `report.json` holds the full data behind both.

## What it measures

- **Fuel** is tokens. Input, output, and cache tokens differ in price by about
  20x, so they are counted and costed separately.
- **The engine** is your harness: model routing, delegation, review regime, effort.
- **Work** is what survives in git: code that shipped and stayed shipped, not
  reverted, rebuilt, or later bug-fixed. It is read at a horizon, so what lasts is
  what counts.

Efficiency is a vector, not a single grade. The setup that wins on one axis rarely
wins on another, so you see the whole picture and pick what matters to you.

## Your numbers are yours

You measure your own engine, for your own improvement. The shared frontier is about
engine craft: which techniques turn tokens into durable work. It never ranks people,
and it never ties efficiency to whether a product won its market, because that is a
bet nobody controls. Contributions are opt-in and anonymized: the technique and the
numbers travel, your identity and your code do not. See
[docs/governance.md](docs/governance.md).

## A commons, not a service

The frontier is a shared record of what works, and it grows as people contribute.
When one person's setup finds a gain, the technique behind it becomes something you
can try on your next run, with the evidence attached. It is early: the public
frontier is small and seeded, so it gets more useful to you as setups like yours
land on it. There is no central service. A frontier is a JSON file plus a viewer;
you keep your own for a project, team, or company, and share upward by hand if you
choose. Third Division Labs keeps the public one. See
[docs/federation.md](docs/federation.md) and [frontier/](frontier/).

## Harness-agnostic by design

Surviving work is a property of git, so the measure is the same for a human, Claude
Code, pi, or OpenCode. Only the token side is harness-specific, and it sits behind a
thin adapter (Claude Code is built; pi and opencode are open slots). Models plug in
through a price registry. Whatever you run, your wins count.
