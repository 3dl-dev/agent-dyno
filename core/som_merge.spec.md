# som_merge.spec.md

`som_merge`, the federated SOM merge: peer-validate the cost field and evaluate a
support-weighted gradient, without any operator disclosing their logs.

## What it is and why it is shaped this way

Item 5 of the SOM plan, redesigned. Operators do NOT pool raw sessions. Each trains
locally against a SHARED REFERENCE CODEBOOK and publishes only two number-grids over
that codebook's lattice: a per-cell cost `field` and a per-cell `support` (session
count), plus an opaque operator tag and the codebook version. This module merges those
contributions into one peer-validated field and reads a confidence-weighted gradient
off it. Federation without disclosure: models and aggregates cross the boundary, never
sessions, sids, repos, feature vectors, days, or transcripts.

The merge is only meaningful because the upstream design makes cell `(r, c)` denote the
same region of setup-space for every operator: item 1's features are shape-only on
FIXED absolute scales (no per-operator normalization), and item 2's init is
deterministic sign-fixed PCA on a pinnable lattice. A shared reference codebook then
pins the frame exactly, so per-cell grids add. Do not break those invariants; they are
what make the grids comparable.

Home: `core/` (harness-neutral, alongside `frontier.py`, the federation engine). Pure
grid arithmetic; NO dependency on the adapters or the trainer. Stdlib only.

## The contribution an operator publishes (`vibrant/som-contribution@1`)

The cost field is a RATIO, `d_per_survkb = dollars / surviving-KB`. You cannot merge
operators by averaging their per-cell ratios: a mean of ratios weighted by session
count is not the pooled ratio, it is a biased estimate, and it breaks the one property
the merge must have (merging a partition of one corpus must reproduce the whole). So
the contribution carries the ratio's NUMERATOR and DENOMINATOR per cell, and the merge
sums them separately. This is also the statistically correct weighting: a cell's cost
is weighted by its surviving work, not by how many sessions happened to land there.

```
{"schema": "vibrant/som-contribution@1",
 "op": "<opaque hash>",              # anonymous operator tag, never an identity
 "codebook_version": "<id>",         # which shared reference codebook this is against
 "lattice": {"rows": R, "cols": C},
 "cost":    [[number >= 0 | null] x C] x R,   # per-cell sum of dollars (the numerator)
 "surv":    [[number >= 0 | null] x C] x R,   # per-cell sum of surviving KB (denominator)
 "support": [[int >= 0] x C] x R}             # per-cell session count
```

The per-cell field is derived, `cost / surv` (null when `surv == 0`); it is never
stored pre-divided. The payload carries no session, no sid, no repo, no vec, no day:
three aggregate grids over the shared lattice, the same privacy class as
`frontier.py` `summarize()`.

## The privacy floor (enforced, tier-0)

`validate_contribution(c) -> [issues]` (sorted, empty if clean). A contribution is
rejected when it:
- is missing `schema`/`op`/`codebook_version`/`lattice`/`cost`/`surv`/`support`, or the
  schema is not `vibrant/som-contribution@1`;
- contains ANY forbidden top-level key (raw-log leakage):
  `FORBIDDEN = {"sessions", "session", "sid", "sids", "repo", "repos", "vec", "vecs",
  "vectors", "day", "days", "date", "dates", "transcript", "transcripts", "path",
  "paths", "identity", "name", "email"}`;
- has `cost`/`surv`/`support` whose shape is not exactly `rows x cols`;
- has a `support` entry that is not a non-negative int, or a `cost`/`surv` entry that
  is not a non-negative finite number or null;
- has a cell where `support == 0` but `cost`/`surv` is not None, or `support > 0` but
  `cost`/`surv` is None (the components must be present exactly when there is support).
  Note `surv` MAY be 0 with `support > 0`: a cell whose sessions produced no surviving
  work has a defined denominator of 0 and an undefined field, which is allowed.

`merge` calls this on every contribution and refuses to merge if any fails (the caller
gets the issues, never a silent partial merge).

## Merge (`merge(contributions) -> merged`)

Requires at least one contribution; all must share the same `lattice` AND
`codebook_version` (else it is an error, raised as `ValueError`, never coerced). Per
cell `(r, c)`, over the operators with `support > 0` there:

```
cost_sum      = sum(cost_op)                                    # pooled numerator
surv_sum      = sum(surv_op)                                    # pooled denominator
field_shared  = cost_sum / surv_sum      if surv_sum > 0 else null   # ratio of sums
weight        = surv_sum                 # surviving work behind the cell (the true weight)
support       = sum(support_op)          # session count (a secondary, intuitive count)
contributors  = count of operators with support_op > 0 there
spread        = max(field_op) - min(field_op) across the operators with surv_op > 0,
                where field_op = cost_op / surv_op            # peer disagreement, null if < 2
```

Summing numerators and denominators separately (not averaging ratios) is what makes the
field the true pooled cost and makes merging a partition reproduce the whole exactly.
The gradient's weight is `surv_sum` (surviving work), not session count, so a cell's
cost carries weight in proportion to the work behind it. A cell with `support == 0` has
`field = null`, `weight = 0`, `support = 0`, `contributors = 0`, `spread = null`. Round
`field`, `weight`, and `spread` to 4 decimals.

Returns:

```
{"schema": "vibrant/som-merged@1",
 "codebook_version": "<id>",
 "lattice": {"rows": R, "cols": C},
 "field_metric": "d_per_survkb",
 "field_lower_is_better": true,
 "operators": [<op hashes, sorted>],
 "field": [[number|null]],       # the peer-validated pooled cost (ratio of sums)
 "weight": [[number]],           # surviving KB behind each cell (the gradient weight)
 "support": [[int]],             # session count behind each cell (secondary)
 "contributors": [[int]],        # how many operators corroborate each cell
 "spread": [[number|null]]}      # cross-operator disagreement per cell
```

## The support-weighted gradient (`merged_gradient`)

`merged_gradient(merged, current_cell, radius=2, min_confidence=3) -> dict | None`.

From `current_cell = [r, c]`, consider cells within Euclidean lattice distance `radius`
(including the current cell) whose `support >= min_confidence` and `field is not None`.
Pick the minimum-field cell (ties: lowest `(r, c)` row-major). If its field is strictly
lower than the current cell's field (when the current cell itself has a field), return
the descent; if the current cell has no field, still return the best supported nearby
cell. Return `None` when no in-radius cell clears `min_confidence`, or when nothing
beats where you already are.

```
{"target_cell": [r, c],
 "vector": [tr - cr, tc - cc],
 "support": <session count behind target>,       # intuitive count
 "weight": <surviving KB behind target>,         # the true statistical weight
 "contributors": <operators corroborating target>,
 "delta": <current_field - target_field or null>}   # expected improvement, >0 is better
```

This is the ask: the field the gradient descends is weighted by surviving work, and the
recommendation carries its own evidence, so a target corroborated by many operators'
real work outweighs a lucky local cell. `support`, `weight`, and `contributors` are the
peer-validation the recommendation carries.

## Bootstrapping the shared frame (`reference_codebook`)

`reference_codebook(som_cache, version) -> dict`. Package a trained `som-cache.json`
(item 2 output) as the publishable reference frame v1:

```
{"schema": "vibrant/som-codebook@1", "version": "<version>",
 "lattice": {...}, "names": [...], "codebook": [[[...]]],
 "hash": "<sha256 of the codebook, 16 hex>"}
```

Deterministic; `version` is caller-supplied and `hash` is derived from the codebook so
a changed frame is detectable. Everyone assigns their sessions to this exact codebook
(via `bmu`, out of band) so their per-cell grids align to the same frame. FedAvg-ing
codebooks across operators is a deliberate NON-goal for v1 (training drift makes it
fragile); the shared reference codebook is the primitive.

## API and constraints

- `SCHEMA_CONTRIB`, `SCHEMA_MERGED`, `SCHEMA_CODEBOOK`, `FORBIDDEN`, module constants.
- `validate_contribution`, `merge`, `merged_gradient`, `reference_codebook`,
  and `contribution(cost, surv, support, codebook_version, lattice, op)` (the producer
  helper that packages ONLY the allowed keys, so a producer cannot leak by accident).
- Stdlib only (`json`, `hashlib`, `math`). Pure functions; deterministic; re-runs
  byte-identical (sorted operators, fixed row-major iteration, rounded floats).
- No em-dashes. `grep -nP '\x{2014}'` clean.

## Known limits

- The shared field is only as aligned as the shared codebook: if operators train
  against different `codebook_version`s their grids are not comparable, which is why
  `merge` refuses to mix versions.
- `spread` is a coarse disagreement signal (range, not variance); enough to flag a cell
  where operators disagree on cost, not a full distribution.
- v1 does not merge codebooks (no FedAvg); the frame is published, not learned jointly.
