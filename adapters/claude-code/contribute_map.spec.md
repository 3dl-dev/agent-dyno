# contribute_map.spec.md

`contribute_map`, the producer for the federated shared map: turn an operator's own
per-session metrics into a shareable `som-contribution@1`, disclosing no logs.

## What it is

The bridge from "my sessions" to "my contribution to the shared map." It reads the
operator's per-session metric dicts (the driver's `--dump-sessions` output) and the
published reference codebook (`vibrant/som-codebook@1`), assigns each session to a cell
on that SHARED frame, and aggregates per-cell cost, surviving work, and count into a
`vibrant/som-contribution@1` payload. That payload is three number-grids the operator
publishes; `core/som_merge.py` merges many of them. No session, sid, repo, vec, or day
leaves in the output: the operator computes locally and ships aggregates.

Assigning to the SHARED reference codebook (not the operator's own trained SOM) is the
whole point: every operator lands their sessions on the same lattice, so the per-cell
grids are comparable and add. See memory `federation-by-model-merge`.

## Input

- `sessions`: a list of per-session metric dicts, exactly the driver's `--dump-sessions`
  output. Reads the same fields `session_features` reads (arms, fanout, n_turns,
  touches, cache split) plus `day`, `dollars`, `born`, `killed`.
- `codebook`: a loaded `vibrant/som-codebook@1` object (`{version, lattice, names,
  codebook, ...}`). Its `names` MUST equal `session_features.FEATURE_NAMES` (same
  feature contract); mismatch is an error, not a silent misalignment.
- `op`: the opaque operator tag to stamp (caller supplied; never derived from identity).
- `window_days` (default 14) and optional `now_day` anchor (default max session day):
  the recency window, matching the driver's field window.

## Method

1. Reject if `codebook["names"] != session_features.FEATURE_NAMES` or the lattice is
   missing/degenerate.
2. Keep sessions with a truthy `day`. Anchor = `now_day` or the max day. Cutoff =
   anchor minus `window_days` (ISO date arithmetic). Keep sessions with `day >= cutoff`.
3. For each kept session `m`: `vec = session_features.features(m)`;
   `(r, c) = som_train.bmu(codebook["codebook"], vec)` (assign on the SHARED frame).
   Accumulate into cell `(r, c)`:
   - `cost += m["dollars"]`
   - `surv += max(m["born"] - m["killed"], 0) / 1024`   (surviving KB)
   - `support += 1`
4. Build `rows x cols` grids: `support` (int per cell), and `cost`/`surv`
   (`round(_, 6)` per cell where `support > 0`, else `null`). A cell with `support > 0`
   always has non-null `cost`/`surv` (possibly `surv == 0.0` when nothing survived).
5. Package with `som_merge.contribution(cost, surv, support, codebook["version"],
   codebook["lattice"], op)` so only the allowed keys leave, and it is valid by
   construction (`som_merge.validate_contribution` returns no issues).

## API

- `SCHEMA_IN = "vibrant/som-codebook@1"`.
- `build(sessions, codebook, op, window_days=14, now_day=None) -> dict`: the
  `som-contribution@1` payload. Pure, deterministic (stable iteration, rounded floats).
- CLI:
  ```
  python3 contribute_map.py --sessions sessions.json --codebook reference-codebook.json
      --op <opaque-tag> [--window-days 14] [--now-day YYYY-MM-DD] [--out contribution.json]
  python3 contribute_map.py --selftest
  ```
  Output is `json.dumps(obj, indent=2, sort_keys=True) + "\n"`.

## Determinism and constraints

- Stdlib only. Imports the sibling `session_features` and `som_train`, and `som_merge`
  from `core/` (add the repo's `core` to the path the same way sibling adapters reach
  shared code, or import by file location). No numpy, no third-party.
- Pure function of `(sessions, codebook, op, window_days, now_day)`; byte-identical
  re-runs.
- No em-dashes. `grep -nP '\x{2014}'` clean.

## Known limits

- The contribution is only comparable to others built against the SAME
  `codebook.version`; `som_merge.merge` refuses to mix versions, and this tool stamps
  the version it assigned against so that check has something to bite on.
- Assignment uses the shared frame, so an operator whose work is unlike the frame's
  training distribution still lands somewhere sensible (nearest cell), just with higher
  quantization error; the field it contributes is still its real cost.
