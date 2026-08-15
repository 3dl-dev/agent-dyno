# som_consume.spec.md

Driver-side consumption of the learned SOM (`som-cache.json`, `vibrant/som@1`).

## What it is

Item 3 of the SOM plan. The trainer (`som_train.py`) runs out of band and writes a
codebook plus a per-session BMU coordinate. This is the STDLIB driver reading that
cache and turning it into what the report and the viz need: the operator's
trajectory across the learned map, the economic field painted over the map cells,
and a downhill gradient. It is a pure consumer: no training, no numpy, deterministic.

It is additive over the hand-written fallback. The existing `rig_space` block (the
hand-written `_embed` trajectory) stays exactly as is. When a SOM cache is present
and joins to the metrics, this attaches a learned `som` sub-block to `rig_space`.
When the cache is absent or joins nothing, `rig_space["som"]` is `None` and the
report is byte-identical to a no-cache run.

## The one alignment rule: the arrow follows the existing recommendation

The map's per-cell field is DESCRIPTIVE (it shades where the good and bad regions
are). It is NOT what the actionable arrow descends. The single actionable move stays
the arm-change from `gradient_move` (the true-economy recommendation, topology
deliberately excluded). The arrow on the map is that same recommendation, projected
into the learned space: it points from the operator's current cell to the region
their OWN sessions that already use the recommended arm occupy. This keeps one
recommendation, topology-excluded by construction, and grounds the arrow in real
data (the operator's actual sonnet sessions, say), never a synthetic point. If the
field alone drove the arrow it could point toward solo cells (lower cost), which
contradicts the deliberate topology exclusion. Field shades; arm-change steers.

## Loading

`load_som(snapshot_dir, path=None) -> dict`: mirror `load_misery` / `load_labels`.
Read `path` if given, else `<snapshot_dir>/som-cache.json` if it exists, else `{}`.
Validate `schema == "vibrant/som@1"`; on any parse error or schema mismatch, return
`{}` (the driver keeps the hand-written fallback, never raises).

## The map: `som_map(metrics, som_cache, move, field_window_days=14, now_day=None)`

Pure function. Returns the `som` block, or `None` when it cannot build one.

Inputs:
- `metrics`: the driver's per-session metric dicts (carry `sid`, `day`, arms
  `engine`/`model`/`worker`/`effort`, and economics `dollars`/`born`/`killed`).
- `som_cache`: the loaded cache (`{}` -> return `None`).
- `move`: the `gradient_move` result, or `None`. Shape when present:
  `{"axis": "orchestrator"|"worker"|"effort", "from": str, "to": str, ...}`.
- `field_window_days`: the field's recency window (the moving frontier). The git
  attribution is all-time; the field is the part that windows.
- `now_day`: optional `YYYY-MM-DD` override for the window anchor (tests). Default:
  the max `day` among joined sessions.

Steps:

1. **Join.** Build `sid -> [r, c]` from `som_cache["sessions"]`. Keep the metrics
   whose `sid` is in the cache AND whose `day` is truthy (undated sessions cannot sit
   on the time trajectory or the windowed field). If nothing joins, return `None`.
   Read `rows`, `cols` from `som_cache["lattice"]`.

2. **Trajectory.** Sort joined sessions by `(day, sid)`. Waypoints are
   `[{"day": day, "cell": [r, c]}, ...]`, downsampled to at most 24 with the driver's
   `_downsample` (always keep the last).

3. **Current cell.** The `[r, c]` of the last waypoint (latest `(day, sid)`).

4. **Field (time-windowed, descriptive).** Anchor = `now_day` or the max joined
   `day`. A session is in-window when `day >= anchor - field_window_days`
   (string dates compare correctly in ISO form; compute the cutoff date with
   `datetime`). For each lattice cell, gather the in-window joined sessions whose BMU
   is that cell and compute the cell field with the driver's `vector(cells)` reading
   `d_per_survkb` (dollars per surviving KB, LOWER is better). `field` is an
   `rows x cols` list of lists; a cell with no in-window sessions, or an undefined
   `d_per_survkb`, is `null`. Round each value to 4 decimals. Also emit
   `support`: the same-shape `rows x cols` grid of in-window session counts (int).

5. **Gradient (the arm-change arrow).** Start from `move`.
   - If `move` is `None`, or its `axis` is not one of `orchestrator`/`worker`/`effort`,
     `gradient` is `{"arm_change": move, "target_cell": null, "vector": null,
     "grounded_in": 0}` (still carries the arm-change for the caller; no arrow).
   - Else map the axis to a metric field: `orchestrator -> model`, `worker -> worker`,
     `effort -> effort`. Gather joined sessions whose value on that field equals
     `move["to"]`. If none, `target_cell`/`vector` are `null`, `grounded_in` is 0.
     If some, `target_cell` is the rounded centroid of their cells
     (`[round(mean_r), round(mean_c)]`), `vector` is
     `[target_cell[0] - current[0], target_cell[1] - current[1]]`, and `grounded_in`
     is the count. The recommended sessions define WHERE on the learned map the
     recommendation lives; the arrow is current -> there.

Output block:

```
{"source": "learned",
 "lattice": {"rows": R, "cols": C},
 "sessions_mapped": <int>,
 "trajectory": [{"day": str, "cell": [r, c]}, ...],
 "current_cell": [r, c],
 "field_metric": "d_per_survkb",
 "field_lower_is_better": true,
 "field_window_days": <int>,
 "field": [[value_or_null x C] x R],
 "support": [[int x C] x R],
 "gradient": {"arm_change": <move or null>, "target_cell": [r, c] or null,
              "vector": [dr, dc] or null, "grounded_in": <int>}}
```

## Wiring

- `rig_space` gains a `som_cache=None` parameter (default `None`, so the existing
  test and any caller that omits it are unchanged). When `som_cache` is truthy it
  computes `som_map(...)` reusing the `move` it already derived from `gradient_move`,
  and sets the returned block's `["som"]` to that map (or `None`).
- `build_report` calls `load_som(snapshot_dir)` and threads the cache into
  `rig_space`. A no-cache run is byte-identical to before.

## Determinism and constraints

- Stdlib only (`json`, `datetime` for the window). Pure functions.
- Stable sorts (`(day, sid)`), fixed row-major cell iteration, floats rounded (field
  to 4). Re-runs byte-identical. The existing `test_vibrant_report.py` determinism
  assertion must stay green.
- No em-dashes. `grep -nP '\x{2014}'` clean.

## Known limits

- The field uses survival-based cost (`d_per_survkb`), the same per-session economics
  the report already trusts, not a git per-commit change count. Consistent with the
  rest of the driver.
- Undated sessions are dropped from the map (they have no place on a time trajectory
  or a windowed field); they remain in the hand-written fallback's aggregate view.
- The arrow is `null` when the operator has no owned sessions at the recommended arm
  (nothing real to point at); the field still renders and the arm-change text still
  stands.
