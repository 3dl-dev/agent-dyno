#!/usr/bin/env python3
"""
Acceptance test for session_features (session_features.spec.md).

The spec made executable. Two kinds of check:
  - known-answer: fixed fixtures with hand-computed expected components.
  - invariant: the load-bearing rule (shape not outcome), one-hot structure,
    range, saturation, purity/determinism.

Run: python3 test_session_features.py   (exit 0 pass, 1 fail)
Stdlib only.
"""
import math
import sys

import session_features as sf


def _approx(a, b, tol=1e-5):
    return abs(a - b) < tol


def _idx(name):
    return sf.FEATURE_NAMES.index(name)


def check(cond, msg, fails):
    if not cond:
        fails.append(msg)


def test_length_and_range(fails):
    m = {"engine": "solo", "routing": "none", "model": "opus-4-8"}
    v = sf.features(m)
    check(len(v) == len(sf.FEATURE_NAMES), f"length {len(v)} != names", fails)
    check(len(sf.FEATURE_NAMES) == 18, f"expected 18 names, got {len(sf.FEATURE_NAMES)}", fails)
    check(all(0.0 <= x <= 1.0 for x in v), f"out of [0,1]: {v}", fails)


def test_onehot(fails):
    m = {"engine": "workflow", "routing": "cross-family", "effort": "high",
         "model": "opus-5", "worker": "sonnet-5"}
    v = sf.features(m)
    eng = sum(v[_idx(n)] for n in ("engine_solo", "engine_delegate", "engine_workflow"))
    rou = sum(v[_idx(n)] for n in ("routing_none", "routing_homogeneous", "routing_cross_family"))
    eff = sum(v[_idx(n)] for n in ("effort_low", "effort_medium", "effort_high",
                                   "effort_xhigh", "effort_max", "effort_unknown"))
    check(_approx(eng, 1.0), f"engine one-hot sum {eng}", fails)
    check(_approx(rou, 1.0), f"routing one-hot sum {rou}", fails)
    check(_approx(eff, 1.0), f"effort one-hot sum {eff}", fails)
    check(v[_idx("engine_workflow")] == 1.0, "engine_workflow not set", fails)
    check(v[_idx("routing_cross_family")] == 1.0, "routing_cross_family not set", fails)
    check(v[_idx("effort_high")] == 1.0, "effort_high not set", fails)


def test_known_answer(fails):
    m = {"engine": "workflow", "routing": "cross-family", "effort": "high",
         "model": "opus-5", "worker": "sonnet-5",
         "fanout": 8, "n_turns": 40, "touches": 10,
         "cache_r": 900, "in_tok": 100, "cache_w": 0}
    v = sf.features(m)
    check(_approx(v[_idx("fanout")], math.log1p(8) / math.log1p(32)),
          f"fanout {v[_idx('fanout')]}", fails)
    check(_approx(v[_idx("turns")], math.log1p(40) / math.log1p(200)),
          f"turns {v[_idx('turns')]}", fails)
    check(_approx(v[_idx("touch_rate")], 0.25), f"touch_rate {v[_idx('touch_rate')]}", fails)
    check(_approx(v[_idx("cache_read_pct")], 0.9), f"cache_read_pct {v[_idx('cache_read_pct')]}", fails)
    # workflow with no recorded depth -> engine fallback = 1 level = 0.25
    check(_approx(v[_idx("depth")], 0.25), f"depth {v[_idx('depth')]}", fails)
    # opus orchestrator + sonnet worker -> two families, even split -> ln(2)/ln(6)
    check(_approx(v[_idx("family_diversity")], math.log(2) / math.log(6)),
          f"family_diversity {v[_idx('family_diversity')]}", fails)


def test_no_capability_tier(fails):
    # v2 removed the tier scalar from the fingerprint entirely.
    check("orch_fire" not in sf.FEATURE_NAMES, "orch_fire not retired", fails)
    check("worker_fire" not in sf.FEATURE_NAMES, "worker_fire not retired", fails)
    check(not hasattr(sf, "TIER"), "TIER constant still present", fails)
    check(sf.SCHEMA == "vibrant/session-features@2", f"schema {sf.SCHEMA}", fails)


def test_solo_defaults(fails):
    m = {"engine": "solo", "routing": "none", "model": "opus-4-8"}
    v = sf.features(m)
    check(v[_idx("engine_solo")] == 1.0, "engine_solo not set", fails)
    check(v[_idx("effort_unknown")] == 1.0, "missing effort not unknown", fails)
    check(v[_idx("cache_read_pct")] == 0.0, "empty cache denom not 0", fails)
    check(v[_idx("fanout")] == 0.0, "no fanout not 0", fails)
    check(v[_idx("depth")] == 0.0, f"solo depth {v[_idx('depth')]}", fails)
    check(v[_idx("family_diversity")] == 0.0,
          f"single-family diversity {v[_idx('family_diversity')]}", fails)


def test_depth_axis(fails):
    # explicit depth wins over the engine fallback and saturates at the cap.
    for d, exp in ((0, 0.0), (1, 0.25), (2, 0.5), (3, 0.75), (4, 1.0), (9, 1.0)):
        v = sf.features({"engine": "workflow", "model": "opus-5", "depth": d})
        check(_approx(v[_idx("depth")], exp), f"depth {d} -> {v[_idx('depth')]} != {exp}", fails)


def test_family_diversity(fails):
    # all one family (any versions of opus) -> 0.0
    v = sf.features({"model": "opus-5", "tree_mix": {"opus-5": 3, "opus-4-8": 2}})
    check(v[_idx("family_diversity")] == 0.0, f"all-opus diversity {v[_idx('family_diversity')]}", fails)
    # opus + a local family (qwen) -> positive, ln(2)/ln(6) at an even split
    v = sf.features({"model": "opus-5", "tree_mix": {"opus-5": 1, "qwen3.8-27b": 1}})
    check(_approx(v[_idx("family_diversity")], math.log(2) / math.log(6)),
          f"opus+qwen diversity {v[_idx('family_diversity')]}", fails)
    # a rich even mix across 6 families saturates near 1.0
    tm = {"opus-5": 1, "sonnet-5": 1, "haiku-4-5": 1, "qwen3.8-27b": 1,
          "llama-3": 1, "gpt-4o": 1}
    v = sf.features({"model": "opus-5", "tree_mix": tm})
    check(_approx(v[_idx("family_diversity")], 1.0), f"6-family diversity {v[_idx('family_diversity')]}", fails)
    # weighted tree_mix with {weight,...} dict entries is read too
    v = sf.features({"tree_mix": {"opus-5": {"weight": 3}, "haiku-4-5": {"weight": 1}}})
    check(v[_idx("family_diversity")] > 0.0, "weighted tree_mix not read", fails)


def test_family_of(fails):
    for model, fam in (("opus-4-8", "opus"), ("claude-sonnet-5", "sonnet"),
                       ("haiku-4-5-20251001", "haiku"), ("qwen3.8-27b", "qwen"),
                       ("opus-5[1m]", "opus")):
        check(sf.family(model) == fam, f"family({model}) = {sf.family(model)} != {fam}", fails)


def test_saturation(fails):
    m = {"engine": "workflow", "routing": "none", "model": "opus-5",
         "fanout": 1000, "n_turns": 5000}
    v = sf.features(m)
    check(v[_idx("fanout")] == 1.0, f"fanout not saturated {v[_idx('fanout')]}", fails)
    check(v[_idx("turns")] == 1.0, f"turns not saturated {v[_idx('turns')]}", fails)


def test_shape_not_outcome(fails):
    """The load-bearing rule: outcome/friction fields MUST NOT move the vector."""
    shape = {"engine": "delegate", "routing": "homogeneous", "effort": "medium",
             "model": "opus-5", "worker": "opus-5", "fanout": 4, "n_turns": 30,
             "touches": 6, "cache_r": 500, "in_tok": 250, "cache_w": 250}
    lean = dict(shape)
    loaded = dict(shape,
                  dollars=99.9, nudges=12, interrupts=7, ends_q=5,
                  born=9000, killed=4000, out_tok=1_000_000, orch_out=800_000,
                  waste_pct=44.0, surv_kb=3.1)
    check(sf.features(lean) == sf.features(loaded),
          "outcome/friction fields changed the vector (shape-not-outcome violated)", fails)


def test_purity_determinism(fails):
    m = {"engine": "workflow", "routing": "cross-family", "effort": "max",
         "model": "opus-5", "worker": "sonnet-5", "fanout": 8, "n_turns": 40,
         "touches": 10, "cache_r": 900, "in_tok": 100, "cache_w": 0}
    snapshot = dict(m)
    v1 = sf.features(m)
    v2 = sf.features(m)
    check(v1 == v2, "features not deterministic", fails)
    check(m == snapshot, "features mutated its input", fails)


def test_feature_matrix(fails):
    sessions = [
        {"sid": "s1", "day": "2026-08-01", "engine": "solo", "routing": "none",
         "model": "opus-4-8"},
        {"sid": "s2", "day": "2026-08-02", "engine": "workflow",
         "routing": "cross-family", "model": "opus-5", "worker": "sonnet-5",
         "fanout": 5, "n_turns": 20},
    ]
    out = sf.feature_matrix(sessions)
    check(out["schema"] == sf.SCHEMA, f"schema {out.get('schema')}", fails)
    check(out["names"] == sf.FEATURE_NAMES, "names mismatch", fails)
    check(len(out["rows"]) == 2, f"rows {len(out['rows'])}", fails)
    r0 = out["rows"][0]
    check(r0["sid"] == "s1" and r0["day"] == "2026-08-01", "row identity wrong", fails)
    check(r0["vec"] == sf.features(sessions[0]), "row vec != features()", fails)
    check(len(r0["vec"]) == len(sf.FEATURE_NAMES), "row vec length", fails)


def main():
    fails = []
    for t in (test_length_and_range, test_onehot, test_known_answer,
              test_no_capability_tier, test_solo_defaults, test_depth_axis,
              test_family_diversity, test_family_of,
              test_saturation, test_shape_not_outcome, test_purity_determinism,
              test_feature_matrix):
        t(fails)
    if fails:
        print("FAIL  session_features:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  session_features: shape-only vector, one-hot arms, fixed scales, "
          "determinism, matrix")
    return 0


if __name__ == "__main__":
    sys.exit(main())
