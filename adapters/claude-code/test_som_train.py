#!/usr/bin/env python3
"""
Acceptance test for som_train (som_train.spec.md).

The spec made executable. Checks:
  - schema/shape: cache object fields, codebook dims, BMU bounds, qe >= 0.
  - determinism: two trains are byte-identical.
  - the real proof: the SOM ORGANIZES. Three separable clusters land on distinct
    lattice cells, and within-cluster BMUs sit closer than between-cluster ones.
  - guards: MIN_SESSIONS, lattice override, the bmu() helper.

Run: python3 test_som_train.py   (exit 0 pass, 1 fail)
Stdlib only (numpy is deliberately not used anywhere in this pipeline).
"""
import json
import math
import sys

import som_train as st

D = 18  # feature width (session-features@1)


def _vec(pairs):
    """An 18-dim vector: dict of index->value, rest 0.0."""
    v = [0.0] * D
    for i, val in pairs.items():
        v[i] = val
    return v


# three well-separated archetypes in shape space
A = _vec({0: 1.0, 3: 1.0, 6: 1.0, 12: 0.15})                       # solo/none/low, haiku
B = _vec({2: 1.0, 5: 1.0, 10: 1.0, 12: 1.0, 13: 0.6, 14: 0.9, 15: 0.8})  # workflow/x-fam/max
C = _vec({1: 1.0, 4: 1.0, 8: 1.0, 12: 0.6, 13: 0.6, 14: 0.4, 15: 0.5})   # delegate/homog/high


def _jitter(v, i):
    """Deterministic tiny perturbation (no RNG), kept small enough to preserve
    cluster separation."""
    out = list(v)
    for k in range(len(out)):
        d = (((i * 7 + k * 3) % 5) - 2) * 0.01
        out[k] = min(1.0, max(0.0, out[k] + d))
    return out


def _matrix(per=12):
    rows = []
    for ci, arche in enumerate((A, B, C)):
        for j in range(per):
            idx = ci * per + j
            rows.append({"sid": f"c{ci}s{j}", "day": f"2026-08-{(idx % 28) + 1:02d}",
                         "vec": _jitter(arche, idx)})
    return {"schema": "vibrant/session-features@1",
            "names": [f"f{i}" for i in range(D)], "rows": rows}


def check(cond, msg, fails):
    if not cond:
        fails.append(msg)


def _grid_dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def test_schema_and_shape(fails):
    cache = st.train(_matrix())
    check(cache["schema"] == "vibrant/som@1", f"schema {cache.get('schema')}", fails)
    check(cache["feature_schema"] == "vibrant/session-features@1",
          f"feature_schema {cache.get('feature_schema')}", fails)
    check(len(cache["names"]) == D, "names not echoed", fails)
    R, Cc = cache["lattice"]["rows"], cache["lattice"]["cols"]
    check(R >= st.MIN_SIDE and Cc >= st.MIN_SIDE, f"lattice too small {R}x{Cc}", fails)
    cb = cache["codebook"]
    check(len(cb) == R and all(len(row) == Cc for row in cb), "codebook rows/cols", fails)
    check(all(len(node) == D for row in cb for node in row), "codebook node width", fails)
    check(all(0.0 <= x <= 1.0 for row in cb for node in row for x in node),
          "codebook out of [0,1]", fails)
    sess = cache["sessions"]
    check(len(sess) == 36, f"sessions {len(sess)}", fails)
    for s in sess:
        r, c = s["bmu"]
        check(0 <= r < R and 0 <= c < Cc, f"bmu out of bounds {s['bmu']}", fails)
        check(s["qe"] >= 0.0, f"qe negative {s['qe']}", fails)
    check(cache["quantization_error"] >= 0.0, "mean qe negative", fails)
    check("params" in cache and cache["params"]["epochs"] == st.EPOCHS, "params missing", fails)


def test_determinism(fails):
    m = _matrix()
    a = json.dumps(st.train(m), sort_keys=True, indent=2)
    b = json.dumps(st.train(m), sort_keys=True, indent=2)
    check(a == b, "train not byte-identical across runs", fails)


def test_input_order_preserved(fails):
    cache = st.train(_matrix())
    sids = [s["sid"] for s in cache["sessions"]]
    check(sids[0] == "c0s0" and sids[-1] == "c2s11", f"order not preserved: {sids[:2]}...", fails)


def test_organizes_clusters(fails):
    """The real proof: separable input organizes onto separated lattice regions."""
    cache = st.train(_matrix())
    sess = cache["sessions"]
    clusters = [[tuple(s["bmu"]) for s in sess if s["sid"].startswith(f"c{ci}")]
                for ci in range(3)]

    # plurality BMU per cluster must be three distinct cells
    plur = []
    for bmus in clusters:
        counts = {}
        for b in bmus:
            counts[b] = counts.get(b, 0) + 1
        plur.append(max(sorted(counts), key=lambda k: counts[k]))
    check(len(set(plur)) == 3, f"clusters share a plurality cell: {plur}", fails)

    # within-cluster spread < between-cluster spread
    def mean_pairwise(pts_a, pts_b):
        ds = [_grid_dist(x, y) for x in pts_a for y in pts_b if x is not y or pts_a is not pts_b]
        return sum(ds) / len(ds) if ds else 0.0

    within = sum(mean_pairwise(c, c) for c in clusters) / 3
    between = sum(mean_pairwise(clusters[i], clusters[j])
                  for i in range(3) for j in range(3) if i < j) / 3
    check(within < between, f"within-cluster spread {within:.2f} >= between {between:.2f}", fails)


def test_min_sessions_guard(fails):
    tiny = {"schema": "vibrant/session-features@1", "names": [f"f{i}" for i in range(D)],
            "rows": [{"sid": f"s{i}", "day": None, "vec": _vec({0: 1.0})} for i in range(3)]}
    raised = False
    try:
        st.train(tiny)
    except ValueError:
        raised = True
    check(raised, "train did not raise on < MIN_SESSIONS rows", fails)


def test_lattice_override(fails):
    cache = st.train(_matrix(), rows=5, cols=6)
    check(cache["lattice"] == {"rows": 5, "cols": 6}, f"override ignored: {cache['lattice']}", fails)
    check(len(cache["codebook"]) == 5 and len(cache["codebook"][0]) == 6,
          "override codebook shape wrong", fails)


def test_bmu_helper(fails):
    # 2x2 codebook; a vector nearest to node (1,0)
    cb = [[[0.0] * D, [1.0] * D],
          [[0.9] + [0.0] * (D - 1), [0.5] * D]]
    target = [1.0] + [0.0] * (D - 1)
    r, c = st.bmu(cb, target)
    check((r, c) == (1, 0), f"bmu picked ({r},{c}), expected (1,0)", fails)


def main():
    fails = []
    for t in (test_schema_and_shape, test_determinism, test_input_order_preserved,
              test_organizes_clusters, test_min_sessions_guard, test_lattice_override,
              test_bmu_helper):
        t(fails)
    if fails:
        print("FAIL  som_train:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  som_train: schema, determinism, cluster organization, guards, bmu")
    return 0


if __name__ == "__main__":
    sys.exit(main())
