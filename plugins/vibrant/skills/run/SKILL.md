---
name: run
description: "Measure your AI coding setup: surviving work per token, from your own logs and git history, on your machine. One number, your worst bottleneck, the change most likely to move it. Nothing uploaded. Use for 'how efficient is my setup' or 'which engine is cheapest per surviving line'."
---

# Run Vibrant on your setup

The numbers come from a deterministic driver, not from you. Your job is to read the
constitution, get the tool onto this machine, run the driver on the operator's
repos, and narrate what it returns. Do not compute vectors, survival, or dollars
yourself. If a number is not in `report.json`, do not report it.

## 1. Get Vibrant onto the machine (once)

Find a Vibrant checkout to run from, in this order:

1. The current directory, if it is the Vibrant repo (it has `core/survival_git.py`).
2. The marketplace clone at `~/.claude/plugins/marketplaces/vibrant` (the whole
   repo lands there when the operator adds the marketplace).
3. Otherwise clone it: `git clone https://github.com/3dl-dev/vibrant ~/.cache/vibrant`.

Then verify the install once, silently, from that checkout:

```
python3 core/test_survival_git.py
python3 skills/vibrant-report/test_vibrant_report.py
```

If either fails, stop and say the install did not verify (name the failure). Do not
report numbers from an unverified build. Run everything below from that checkout.

## 2. Read the constitution first (gating)

Read `docs/governance.md`. You measure the operator's **own engine** for
self-improvement. Never rank an individual against product outcomes, never compare
people. If asked for that, decline and cite the document. The driver stamps
`report.json` governance-clean; do not emit anything that contradicts it.

## 3. Ask what to measure

Do NOT hand-pick the repos. The driver discovers them from the snapshot itself:
`--repos auto` (the default) reads every project the operator's sessions worked in
and maps each to a git repo under `--repos-root` (default `~/projects`). Measuring
only the repos you happened to name is how the tool once reported 9% of a rig as the
whole thing; auto-discovery removes that failure. Pass explicit `--repos a,b,c` only
if the operator asks to narrow it. Set `--repos-root` if their repos live elsewhere.

The report carries a `coverage` block and, when it covers under 90% of sessions,
prints a banner naming the unmeasured projects. If you see it, tell the operator and
widen `--repos-root` or add the missing repos: the number only means something over
the work it actually looked at. Ask the window (default `30.days.ago`).

A first run tops out near a month because the fuel side comes from harness
transcripts, which rotate after ~30 days; the surviving-work numerator (git) is not
capped. If they want a longer engine timeline, point them at "Building history past
~30 days" in `docs/getting-started.md`: a weekly `snapshot.py` cron freezes the fuel
before it rotates.

## 4. Build the fuel snapshot and run the driver

```
python3 adapters/claude-code/snapshot.py --out <snap-parent>
python3 skills/vibrant-report/vibrant_report.py --harness claude-code \
    --snapshot <snap-dir> --repos auto --repos-root ~/projects \
    --since <window> --out <out-dir>
```

Reuse a recent snapshot dir if one exists. The driver writes `report.json` (the
contract), `report.md` (the surface), and `report.html` (the charts).

The report compares the operator against their **configured frontier**: the driver
reads `$VIBRANT_FRONTIER` (a path or a URL) when `--frontier` is not passed, else the
repo's own. An operator on a team or in an enterprise sets `$VIBRANT_FRONTIER` to their
internal frontier (a shared file or a URL), so the same-shape comparison and the
lever are drawn from their own group, and nothing about their repos leaves to get
that comparison.

## 5. Present the surface, and only the surface

Show `report.md`: the one number (`topline.eq`), the one lever, the measure line if
they passed `--baseline`, and the compact timeline. Point them at `report.html` for
the charts. Do **not** narrate the vector, the same-shape cells, the claims, or the
confounds; that machinery lives in `report.json` for anyone who asks. Survival is
not value; if you add one caveat, that is the one. Keep it short.

To rerun after a change and see if the number moved, run again with
`--baseline <prev report.json>`.

## 6. Turn the lever into a change in THEIR setup (the payoff)

A generic lever ("have the orchestrator review the worker before accepting") is not
the value. The value is telling THIS operator the one thing to change in THEIR own
toolkit to get it. Do this only when `report.json` has a `lever` (skip it when the
operator already leads their frontier and there is none).

1. Read their actual rig, in this order, and stop when you have enough to be
   specific: their `CLAUDE.md` (global `~/.claude/CLAUDE.md` and the project's), their
   skills (`~/.claude/skills/` and `.claude/skills/`), their agent specs
   (`.claude/agents/`), their hooks (`.claude/settings.json`), and whatever they
   orchestrate with (an `rd`-style board, `swarm`/`delegate` skills, custom scripts).
   Everyone's rig is different; read theirs, do not assume mine.
2. Translate the lever into one to three concrete edits in files they actually have,
   each naming the file and the change: the skill to edit, the exact `CLAUDE.md` rule
   to add (give the line), the hook or agent spec to change. Example, lever "tighten
   the review pass behind fan-out": if they have a `swarm-dispatch` skill, "add a
   review stage that diff-checks each worker's return before accepting"; if they have
   no such skill, "add to your project `CLAUDE.md`: after a delegate returns, review
   its diff before you build on it." Ground every suggestion in something on disk.
3. Offer to make the edit; do not change their files without a yes. If their rig is
   too thin to place the lever, say so plainly instead of inventing tooling for them.

## 7. Offer to contribute (in the flow, opt-in)

Contributing is part of using Vibrant, not a separate errand. After you show the
surface, ask the operator plainly: "Want to add this run to your frontier? It is
anonymized, engine fingerprint and numbers only, and it goes to your own frontier,
not a public one, unless you say so." If they say yes, do the
`/vibrant:contribute` steps inline against their configured frontier
(`$VIBRANT_FRONTIER`, else the local file). If they say no, stop; publishing is never a
side effect of a run. The default target is always their own scope; a push to any
parent is a separate, explicit choice.
