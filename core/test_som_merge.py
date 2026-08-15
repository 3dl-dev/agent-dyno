#!/usr/bin/env python3
"""
Acceptance test for som_merge (som_merge.spec.md): the federated SOM merge.

The spec made executable, with hand-computed answers. Contributions carry the cost
ratio's numerator (cost) and denominator (surv) per cell, so the merge sums them
separately: that is the only way a mean over operators equals the pooled cost, which
this test pins with a partition-invariance check. Also checks the confidence-weighted
gradient and the privacy floor that keeps raw logs from crossing the boundary.

Run: python3 test_som_merge.py   (exit 0 pass, 1 fail)
Stdlib only.
"""
import json
import sys

import som_merge as sm

V = "cb-v1"


def _contrib(op, cost, surv, support, version=V, rows=2, cols=2):
    return {"schema": "vibrant/som-contribution@1", "op": op,
            "codebook_version": version, "lattice": {"rows": rows, "cols": cols},
            "cost": cost, "surv": surv, "support": support}


# two operators over a 2x2 shared codebook. field_op = cost/surv per cell.
A = _contrib("opA", [[20.0, None], [80.0, 5.0]], [[2.0, None], [4.0, 1.0]], [[6, 0], [7, 3]])
B = _contrib("opB", [[90.0, 40.0], [None, 45.0]], [[3.0, 1.0], [None, 3.0]], [[9, 4], [0, 8]])


def check(cond, msg, fails):
    if not cond:
        fails.append(msg)


def test_validate_clean(fails):
    check(sm.validate_contribution(A) == [], f"A not clean: {sm.validate_contribution(A)}", fails)
    check(sm.validate_contribution(B) == [], f"B not clean: {sm.validate_contribution(B)}", fails)
    # surv == 0 with support > 0 is allowed (sessions, no surviving work, field undefined)
    ok = _contrib("z", [[1.0, None], [1.0, 1.0]], [[0.0, None], [1.0, 1.0]], [[3, 0], [1, 1]])
    check(sm.validate_contribution(ok) == [], f"surv0-with-support rejected: {sm.validate_contribution(ok)}", fails)


def test_privacy_floor(fails):
    leak = dict(A, sessions=[{"sid": "x"}])
    check(any("sessions" in s for s in sm.validate_contribution(leak)), "leak key not caught", fails)
    for k in ("sid", "repo", "vec", "day", "transcript", "path", "email"):
        bad = dict(A)
        bad[k] = "anything"
        check(sm.validate_contribution(bad), f"forbidden key {k} not rejected", fails)


def test_validate_shape_and_consistency(fails):
    check(sm.validate_contribution(dict(A, cost=[[1.0]])), "bad cost shape passed", fails)
    # support 0 but components present
    check(sm.validate_contribution(_contrib("z", [[1.0, None], [1.0, 1.0]],
                                            [[1.0, None], [1.0, 1.0]], [[0, 0], [1, 1]])),
          "support0-components-present passed", fails)
    # support >0 but component null
    check(sm.validate_contribution(_contrib("z", [[None, None], [1.0, 1.0]],
                                            [[1.0, None], [1.0, 1.0]], [[2, 0], [1, 1]])),
          "support>0-cost-null passed", fails)
    # negative support / negative cost
    check(sm.validate_contribution(_contrib("z", [[1.0, None], [1.0, 1.0]],
                                            [[1.0, None], [1.0, 1.0]], [[-1, 0], [1, 1]])),
          "negative support passed", fails)
    check(sm.validate_contribution(_contrib("z", [[-1.0, None], [1.0, 1.0]],
                                            [[1.0, None], [1.0, 1.0]], [[1, 0], [1, 1]])),
          "negative cost passed", fails)


def test_merge_math(fails):
    m = sm.merge([A, B])
    check(m["schema"] == "vibrant/som-merged@1", "merged schema", fails)
    check(m["operators"] == ["opA", "opB"], f"operators {m['operators']}", fails)
    f = m["field"]
    # (0,0): 110/5 = 22.0 ; (1,1): 50/4 = 12.5 ; (0,1) B only 40/1 ; (1,0) A only 80/4
    check(f == [[22.0, 40.0], [20.0, 12.5]], f"field {f}", fails)
    check(m["weight"] == [[5.0, 1.0], [4.0, 4.0]], f"weight {m['weight']}", fails)
    check(m["support"] == [[15, 4], [7, 11]], f"support {m['support']}", fails)
    check(m["contributors"] == [[2, 1], [1, 2]], f"contributors {m['contributors']}", fails)
    # spread: (0,0) |30-10|=20, (1,1) |15-5|=10, single-contributor cells null
    check(m["spread"][0][0] == 20.0 and m["spread"][1][1] == 10.0, f"spread {m['spread']}", fails)
    check(m["spread"][0][1] is None and m["spread"][1][0] is None,
          f"single-op spread not null: {m['spread']}", fails)


def test_partition_invariance(fails):
    """Merging a partition of one corpus must reproduce the whole corpus's field.
    This is the property that a mean-of-ratios violates and a ratio-of-sums preserves."""
    whole = _contrib("whole", [[110.0, 40.0], [80.0, 50.0]],
                     [[5.0, 1.0], [4.0, 4.0]], [[15, 4], [7, 11]])
    whole_field = [[round(whole["cost"][r][c] / whole["surv"][r][c], 4)
                    for c in range(2)] for r in range(2)]
    merged = sm.merge([A, B])["field"]
    check(merged == whole_field,
          f"partition merge {merged} != whole {whole_field}", fails)


def test_merge_rejects_mismatch(fails):
    other = _contrib("opC", [[1.0, 1.0], [1.0, 1.0]], [[1.0, 1.0], [1.0, 1.0]],
                     [[1, 1], [1, 1]], version="cb-v2")
    for bad_set, label in (([A, other], "version"), ([A, dict(B, sessions=[1])], "leaky")):
        raised = False
        try:
            sm.merge(bad_set)
        except ValueError:
            raised = True
        check(raised, f"{label} mismatch not rejected", fails)


def test_gradient(fails):
    m = sm.merge([A, B])
    # from (0,0) field 22; min_confidence 7 on session support excludes (0,1) support 4
    g = sm.merged_gradient(m, [0, 0], radius=2, min_confidence=7)
    check(g is not None, "gradient None unexpectedly", fails)
    if g:
        check(g["target_cell"] == [1, 1], f"target {g['target_cell']}", fails)
        check(g["vector"] == [1, 1], f"vector {g['vector']}", fails)
        check(g["support"] == 11, f"support {g['support']}", fails)
        check(g["weight"] == 4.0, f"weight {g['weight']}", fails)
        check(g["contributors"] == 2, f"contributors {g['contributors']}", fails)
        check(abs(g["delta"] - 9.5) < 1e-9, f"delta {g['delta']}", fails)


def test_gradient_radius_and_confidence(fails):
    m = sm.merge([A, B])
    g = sm.merged_gradient(m, [0, 0], radius=1, min_confidence=7)  # (1,1) out of radius
    check(g and g["target_cell"] == [1, 0], f"radius1 target {g and g['target_cell']}", fails)
    check(sm.merged_gradient(m, [0, 0], radius=2, min_confidence=16) is None,
          "high min_confidence should yield None", fails)


def test_reference_codebook(fails):
    cache = {"lattice": {"rows": 2, "cols": 2}, "names": ["f0", "f1"],
             "codebook": [[[0.1, 0.2], [0.3, 0.4]], [[0.5, 0.6], [0.7, 0.8]]]}
    ref = sm.reference_codebook(cache, "v1")
    check(ref["schema"] == "vibrant/som-codebook@1", "codebook schema", fails)
    check(ref["version"] == "v1" and ref["lattice"] == {"rows": 2, "cols": 2}, "version/lattice", fails)
    check(len(ref["hash"]) == 16, f"hash len {len(ref['hash'])}", fails)
    check(sm.reference_codebook(cache, "v1") == ref, "reference_codebook not deterministic", fails)


def test_contribution_producer(fails):
    c = sm.contribution([[1.0, None], [2.0, 3.0]], [[1.0, None], [1.0, 1.0]],
                        [[1, 0], [1, 1]], V, {"rows": 2, "cols": 2}, "opX")
    check(set(c.keys()) == {"schema", "op", "codebook_version", "lattice", "cost", "surv", "support"},
          f"producer leaked keys: {sorted(c.keys())}", fails)
    check(sm.validate_contribution(c) == [], f"produced contribution invalid: {sm.validate_contribution(c)}", fails)


def test_determinism(fails):
    a = json.dumps(sm.merge([A, B]), sort_keys=True)
    b = json.dumps(sm.merge([B, A]), sort_keys=True)  # operator order must not matter
    check(a == b, "merge not order-independent / deterministic", fails)


def main():
    fails = []
    for t in (test_validate_clean, test_privacy_floor, test_validate_shape_and_consistency,
              test_merge_math, test_partition_invariance, test_merge_rejects_mismatch,
              test_gradient, test_gradient_radius_and_confidence, test_reference_codebook,
              test_contribution_producer, test_determinism):
        t(fails)
    if fails:
        print("FAIL  som_merge:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  som_merge: privacy floor, ratio-of-sums merge, partition-invariance, "
          "weighted gradient, determinism")
    return 0


if __name__ == "__main__":
    sys.exit(main())
