# session_features.spec.md

`session_features`, the per-session feature extractor for the learned SOM.

## What it is

The SOM (item 2, `som_train.py`) learns a low-dimensional organization of the
operator's sessions from a feature vector per session. This tool produces that
vector. It is the grain change that the rig-space handoff calls for: the unit is a
single session (232 local, thousands federated), not one of the 12 rig-configs.

It is the learned upgrade's front door. The hand-written `_embed` in the driver
(`vibrant_report.py`, the `_FAN`/`_FIRE`/`_RIGOR` priors) stays as the fallback;
this extractor is what a learner reads instead of those priors.

## The one load-bearing rule: shape, not outcome

The vector encodes a session's **shape**: the configuration arms the operator chose
and the working-style topology those choices produced. It MUST NOT encode the
economic outcome (surviving work, dollars, efficiency, bloat) or the operator's
friction (misery, nudges, interrupts). Those are the **field** painted over the
learned map by the driver (item 3), and the gradient descends that field. If
outcome leaks into the features, the SOM organizes sessions partly by their verdict,
and "move to a better-region cell" stops meaning "change your setup." Shape in,
field over the top, gradient down the field. Keep them separate.

Concretely: friction signals present on the session metric dict (`nudges`,
`interrupts`, `ends_q`, `waste`/`killed`, `dollars`, `born`, `out_tok` as a volume)
are NOT features. Working-style signals the operator's *choices* produce (how wide
they fan out, how long sessions run, how much they touch the loop, their cache
posture) ARE features.

## Input

A list of per-session metric dicts, exactly the shape the driver already builds in
`vibrant_report.py` (`metric()`, the dict returned around the `"sid"` key). The
fields this tool reads:

- `sid` (str), `day` (str or null): identity and time. Carried through, not featurized.
- `engine` (str): `solo` | `delegate` | `workflow`.
- `routing` (str): `none` | `homogeneous` | `cross-family`.
- `effort` (str or null): `low` | `medium` | `high` | `xhigh` | `max`, else unknown.
- `model` (str): orchestrator model base (e.g. `opus-4-8`, `sonnet-5`).
- `worker` (str or null): worker model base, or `solo`/absent when not delegating.
- `fanout` (int): subagents dispatched (`wf_agents + plain_agents`).
- `n_turns` (int): assistant turns in the session.
- `touches` (int): turns the operator typed into (engagement).
- `cache_r`, `in_tok`, `cache_w` (int): read-side token split, for cache posture.

Unknown or missing fields fall to a defined default (below); the tool never raises
on a sparse dict.

## Output: the feature vector

`features(m)` returns a list of floats, all in `[0, 1]`, of length
`len(FEATURE_NAMES)`. Every component is computed by a **fixed absolute transform**,
never a corpus-relative one (no min-max over the batch, no z-score). Fixed scales
make two operators' vectors directly comparable on one shared map, which the
federated map (item 5) requires, and make the vector a pure function of the single
session with no batch dependency.

`FEATURE_NAMES` (order is the vector order; the schema pins it):

Categorical, one-hot (a recognized value sets its slot to 1.0, all siblings 0.0; an
unrecognized/missing value sets the reserved slot, e.g. `effort_unknown`, or leaves
all engine/routing slots 0.0 if truly absent):

1. `engine_solo`
2. `engine_delegate`
3. `engine_workflow`
4. `routing_none`
5. `routing_homogeneous`
6. `routing_cross_family`
7. `effort_low`
8. `effort_medium`
9. `effort_high`
10. `effort_xhigh`
11. `effort_max`
12. `effort_unknown`

Continuous, each already in `[0, 1]` by a fixed transform:

13. `orch_fire`: orchestrator model tier from the fixed `TIER` map (below). Missing
    model -> 0.5.
14. `worker_fire`: worker model tier from `TIER`, or 0.0 when solo / no worker /
    worker == `solo`.
15. `fanout`: `min(log1p(fanout) / log1p(FANOUT_CAP), 1.0)`, `FANOUT_CAP = 32`.
16. `turns`: `min(log1p(n_turns) / log1p(TURNS_CAP), 1.0)`, `TURNS_CAP = 200`.
17. `touch_rate`: `min(touches / max(n_turns, 1), 1.0)`.
18. `cache_read_pct`: `cache_r / (cache_r + in_tok + cache_w)`, or 0.0 when the
    denominator is 0.
19. `out_per_turn`: this is a **volume/verbosity of the engine's own output**, a
    style signal, not an economic outcome; it is derived from `orch_out` only if
    present, else omitted. To keep the vector purely shape and avoid any token-volume
    that reads as productivity, `out_per_turn` is NOT included. (Slot intentionally
    left out; see note.) 

Note on component 19: the first build ships 18 features (1 to 18). `out_per_turn`
was considered and rejected to keep the vector clean of anything that could be read
as "more output = better." If a future spec revision adds it, it lands as a new
schema version, not a silent append.

### The TIER map (fixed, absolute, federation-shared)

Mirror the driver's firepower ordering so the learned space and the fallback agree
on tier direction. In `[0, 1]`:

```
TIER = {
  "haiku-4-5": 0.15, "haiku-4-5-20251001": 0.15, "fable-5": 0.25,
  "sonnet-4-6": 0.55, "sonnet-5": 0.6, "opus-4-6": 0.85, "opus-4-8": 0.9,
  "opus-5": 1.0,
}
```

An unrecognized worker/orchestrator base maps to 0.5 (orchestrator) or, for a
worker, 0.0 only when there is genuinely no worker; an unrecognized *named* worker
maps to 0.5. Base the model string with the same `.split("[")[0]` /
`replace("claude-", "")` normalization the adapters already use.

## API

- `SCHEMA = "vibrant/session-features@1"`.
- `FEATURE_NAMES`: the ordered list above (length 18).
- `TIER`, `FANOUT_CAP`, `TURNS_CAP`: module constants.
- `features(m: dict) -> list[float]`: pure, deterministic, length `len(FEATURE_NAMES)`,
  every element in `[0, 1]`. No batch, no corpus, no randomness.
- `feature_matrix(sessions: list[dict]) -> dict`: returns
  `{"schema": SCHEMA, "names": FEATURE_NAMES, "rows": [{"sid","day","vec"}, ...]}`,
  rows in input order (the caller sorts). `vec` is the `features()` output.

## CLI

```
python3 session_features.py --sessions sessions.json [--out matrix.json]
python3 session_features.py --selftest
```

`--sessions` is a JSON array of per-session metric dicts (what the driver builds; a
`--dump-sessions` path on the driver or an equivalent extractor supplies it). Output
is the `feature_matrix` object, `json.dumps(..., indent=2, sort_keys=True)`, written
to `--out` or stdout. `--selftest` runs the acceptance fixture, exits 0/1.

## Determinism and constraints

- Stdlib only. Pure arithmetic; `math.log1p`. No numpy in this tool (the trainer that
  consumes it may use numpy; this front door stays stdlib so the driver could import
  it too if a future item wants live projection).
- `features()` is a pure function of one dict. `feature_matrix` is a pure function of
  the list. Re-running on the same input is byte-identical.
- No em-dashes anywhere.

## Known limits

- Fixed caps (`FANOUT_CAP=32`, `TURNS_CAP=200`) saturate the extremes; a session with
  400 turns and one with 200 both read 1.0 on `turns`. That is deliberate: the tail is
  rare and the SOM cares about organization, not the exact magnitude of an outlier.
- The vector is shape only by design; a reader wanting to know if a shape *paid off*
  must join to the field (the driver's per-cell economics), which is exactly the
  separation the SOM depends on.
