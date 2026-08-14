---
name: run
description: "Measure your AI coding setup: surviving work per token, from your own logs and git history, on your machine. One number, your worst bottleneck, the change most likely to move it. Nothing uploaded. Use for 'how efficient is my setup' or 'which engine is cheapest per surviving line'."
---

# Run Agent Dyno on your setup

The numbers come from a deterministic driver, not from you. Your job is to read the
constitution, get the tool onto this machine, run the driver on the operator's
repos, and narrate what it returns. Do not compute vectors, survival, or dollars
yourself. If a number is not in `report.json`, do not report it.

## 1. Get Agent Dyno onto the machine (once)

Find an Agent Dyno checkout to run from, in this order:

1. The current directory, if it is the agent-dyno repo (it has `core/survival_git.py`).
2. The marketplace clone at `~/.claude/plugins/marketplaces/agent-dyno` (the whole
   repo lands there when the operator adds the marketplace).
3. Otherwise clone it: `git clone https://github.com/3dl-dev/agent-dyno ~/.cache/agent-dyno`.

Then verify the install once, silently, from that checkout:

```
python3 core/test_survival_git.py
python3 skills/dyno-report/test_dyno_report.py
```

If either fails, stop and say the install did not verify (name the failure). Do not
report numbers from an unverified build. Run everything below from that checkout.

## 2. Read the constitution first (gating)

Read `docs/governance.md`. You measure the operator's **own engine** for
self-improvement. Never rank an individual against product outcomes, never compare
people. If asked for that, decline and cite the document. The driver stamps
`report.json` governance-clean; do not emit anything that contradicts it.

## 3. Ask what to measure

Ask the operator which repos they actually code in (comma-separated paths); default
to the current git repo if they are in one. Ask the window (default `30.days.ago`).

## 4. Build the fuel snapshot and run the driver

```
python3 adapters/claude-code/snapshot.py --out <snap-parent>
python3 skills/dyno-report/dyno_report.py --harness claude-code \
    --snapshot <snap-dir> --repos <their-repos> --since <window> --out <out-dir>
```

Reuse a recent snapshot dir if one exists. The driver writes `report.json` (the
contract), `report.md` (the surface), and `report.html` (the charts).

## 5. Present the surface, and only the surface

Show `report.md`: the one number (`topline.eq`), the one lever, the measure line if
they passed `--baseline`, and the compact timeline. Point them at `report.html` for
the charts. Do **not** narrate the vector, the same-shape cells, the claims, or the
confounds; that machinery lives in `report.json` for anyone who asks. Survival is
not value; if you add one caveat, that is the one. Keep it short.

To rerun after a change and see if the number moved, run again with
`--baseline <prev report.json>`.

## 6. Contribute (opt-in, separate)

Publishing is never a side effect of a run. If the operator wants to add an
anonymized result to a frontier, that is the deliberate `/agent-dyno:contribute`
step, with their explicit consent.
