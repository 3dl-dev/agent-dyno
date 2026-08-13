# hoist: agent-dyno ships itself

`config.json` here is agent-dyno's Layer 2 [hoistable](../../hoistable) config: the
formula that installs agent-dyno on a clean machine with zero setup. On install it
clones the repo, renders a report, and grades the result, so a fresh target ends at
a rendered `report.html`, not a blank prompt.

## Run it

```
# from a machine with the hoist skill (see ~/projects/hoistable)
hoist agent-dyno
# or directly, against this config:
python3 <hoistable>/hoist/hoist.py <agent-dyno>/hoist/config.json
```

The `default` profile is **hermetic** (`isolation.none`): everything happens inside
a throwaway clone. `bringup` runs `skills/dyno-report/demo.py`, which fabricates its
own synthetic snapshot and a throwaway git repo and renders `report.{json,md,html}`
into `.hoist-report/` (no harness transcripts, no network, no keys, no real repos).
`acceptance` then re-runs the stdlib self-tests (numerator, driver, evidence,
demo) and confirms the rendered chart carries the topline. Nothing leaves the
machine.

## Try the render on its own

```
python3 skills/dyno-report/demo.py --out /tmp/dyno-demo
open /tmp/dyno-demo/report.html
```

## Source of truth

This file is the canonical config. The hoistable index points across at it
(`point don't embed`), so there is one copy to keep honest. To distribute publicly,
swap `source.clone` for the repo's public URL.
