# som_train.spec.md

`som_train`, the out-of-band Self-Organizing Map trainer for the learned fingerprint.

## What it is and where it sits

The rig-space fingerprint is a trajectory in a low-dimensional latent space. The
hand-written `_embed` in the driver places sessions by prior; this tool *learns* the
low-D organization from the data instead. It reads the per-session shape vectors from
`session_features` (schema `vibrant/session-features@1`), trains a Kohonen SOM, and
writes a `som-cache.json` the stdlib driver consumes deterministically (item 3). It
never runs inside the driver: this is the out-of-band step in the same
inference -> cache -> driver-consumes seam that misery and the fingerprint labels use.

The learned map is additive over the hand-written fallback. When the cache is
present the driver uses the learned BMU coordinates; when it is absent, or a session
is not in it, the driver falls back to `_embed`.

## Why stdlib, not numpy

The plan allowed numpy for this out-of-band step. This build is pure Python 3
stdlib anyway, for two reasons that outweigh the convenience:

1. **Byte-identical determinism.** The repo requires re-runs to be byte-identical.
   numpy on top of a threaded BLAS can produce tiny run-to-run float differences from
   nondeterministic reduction order. Pure Python float math with a fixed iteration
   order does not.
2. **Portability.** No install; the trainer runs anywhere the driver does.

A SOM is small vector arithmetic; it does not need numpy.

## Input

The `session_features` matrix JSON:

```
{"schema": "vibrant/session-features@1",
 "names": [... 18 feature names ...],
 "rows": [{"sid": str, "day": str|null, "vec": [float x 18]}, ...]}
```

The tool reads `names`, `rows`, and echoes the input `schema` into its output as
`feature_schema`. It requires at least `MIN_SESSIONS = 5` rows; below that it exits
with a clear error (the driver keeps the hand-written fallback in that case).

## Method (deterministic Kohonen, batch, PCA-oriented init)

Let `N` = number of rows, `D` = number of features, and the lattice be `R x C` nodes.

1. **Lattice size.** If `--rows`/`--cols` are given, use them (the federated trainer
   pins these so every operator shares one map). Otherwise derive a square-ish grid
   from the Vesanto heuristic: `units = 5 * sqrt(N)`, `side = round(sqrt(units))`,
   clamped to `[MIN_SIDE=4, MAX_SIDE=12]`, and `R = C = side`. Record the resolved
   `rows`, `cols` in the cache.

2. **Deterministic PCA init.** Compute the data mean and the top two principal
   directions by **power iteration with deflation** on the `D x D` covariance matrix
   (deterministic: fixed start vector `[1,0,0,...]`, fixed iteration count
   `POWER_ITERS = 100`; after each component, fix its sign so its largest-magnitude
   entry is positive, removing the SVD sign ambiguity). Initialize node `(r, c)` to
   `mean + a_r * pc1 + b_c * pc2`, where `a_r`, `b_c` spread linearly over
   `[-1, 1]` scaled by `sqrt(eigenvalue)` of each component. Clamp init values to
   `[0, 1]` (features are bounded). This makes the map's axes correspond to the
   dominant shape variation, which the viz (item 4) and the shared map (item 5) rely
   on. If the data is degenerate (a principal direction has ~0 eigenvalue), fall back
   to spreading that axis over a small fixed epsilon so nodes are not all identical.

3. **Batch training.** For `EPOCHS = 20` epochs:
   - **Assign** each sample to its Best Matching Unit (BMU): the node minimizing
     squared Euclidean distance. Ties break by lowest `(r, c)` in row-major order.
   - **Neighborhood.** Radius decays exponentially from `sigma0 = max(R, C) / 2` to
     `sigma_final = 0.7`: `sigma(t) = sigma0 * (sigma_final / sigma0) ** (t / (EPOCHS - 1))`.
     Node-to-node influence `h(i, j) = exp(-grid_dist2(i, j) / (2 * sigma(t)**2))`,
     `grid_dist2` the squared Euclidean distance on the lattice coordinates.
   - **Update (batch).** New node weight = the `h`-weighted mean of all samples,
     weighted by `h(bmu(sample), node)`:
     `w_node = sum_s h(bmu_s, node) * x_s / sum_s h(bmu_s, node)`.
     A node with zero total weight (no sample in range) keeps its previous weight.
   Batch training has no learning rate and no sample-ordering dependence, so it is
   deterministic without a seed. A `--seed` flag is accepted for interface stability
   and recorded, but the default batch path does not consume it.

4. **Final assignment.** After training, assign every session its BMU `[r, c]` and its
   quantization error `qe` (Euclidean distance to the BMU weight).

## Output: som-cache.json

```
{"schema": "vibrant/som@1",
 "feature_schema": "vibrant/session-features@1",
 "names": [... echoed feature names ...],
 "lattice": {"rows": R, "cols": C},
 "params": {"epochs": 20, "sigma0": ..., "sigma_final": 0.7, "seed": <seed>,
            "power_iters": 100, "min_sessions": 5},
 "codebook": [[[float x D], ... C nodes ...], ... R rows ...],
 "sessions": [{"sid": str, "day": str|null, "bmu": [r, c], "qe": float}, ...],
 "quantization_error": <mean qe over sessions>}
```

- `codebook[r][c]` is the `D`-length weight vector of node `(r, c)`.
- `sessions` is in input row order.
- All floats rounded to `ROUND = 6` decimals for byte-stable JSON.
- Serialized `json.dumps(obj, indent=2, sort_keys=True) + "\n"`.

## API

- `SCHEMA = "vibrant/som@1"`.
- Constants: `MIN_SESSIONS=5`, `MIN_SIDE=4`, `MAX_SIDE=12`, `EPOCHS=20`,
  `POWER_ITERS=100`, `SIGMA_FINAL=0.7`, `ROUND=6`.
- `train(matrix: dict, rows=None, cols=None, seed=0) -> dict`: the pure trainer;
  returns the cache object. Deterministic given `(matrix, rows, cols, seed)`.
- `bmu(codebook, vec) -> (r, c)`: exposed for the driver/tests (pure).
- CLI:
  ```
  python3 som_train.py --features matrix.json [--rows R --cols C] [--seed S] [--out som-cache.json]
  python3 som_train.py --selftest
  ```
  `--features` is the `session_features` matrix JSON. Output to `--out` or stdout.
  `--selftest` runs the acceptance fixture, exits 0/1.

## Determinism and constraints

- Python 3 stdlib only (`math`, `json`, `argparse`). No numpy, no third-party.
- `train()` is a pure function of its inputs; two runs are byte-identical.
- All lattice/codebook iteration uses fixed row-major order so float reductions are
  reproducible.
- No em-dashes anywhere. Verify `grep -nP '\x{2014}' som_train.py` is empty.

## Known limits

- Batch SOM with 20 epochs on a small corpus is fast but coarse; the map organizes,
  it does not perfectly separate. That is acceptable: the driver paints the economic
  field over cells and reads a gradient, it does not need crisp cluster boundaries.
- PCA init by power iteration is exact enough for orientation; it is not a full
  eigensolver. For near-degenerate data it uses the epsilon fallback so the map is
  never all one point.
- Lattice size is data-derived by default; the federated map (item 5) MUST pin
  `--rows`/`--cols` so every operator trains onto the same grid.
