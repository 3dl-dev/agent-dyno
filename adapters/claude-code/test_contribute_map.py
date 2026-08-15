#!/usr/bin/env python3
"""
Acceptance test for contribute_map (contribute_map.spec.md): the producer that turns
an operator's per-session metrics into a shareable som-contribution, no logs disclosed.

Builds a reference codebook whose nodes ARE two sessions' feature vectors, so BMU
assignment is exact and the per-cell aggregation is hand-checkable.

Run: python3 test_contribute_map.py   (exit 0 pass, 1 fail)
Stdlib only.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "core"))

import session_features as sf
import contribute_map as cm
import som_merge as smg


def check(cond, msg, fails):
    if not cond:
        fails.append(msg)


# two distinct sessions -> distinct feature vectors
SA = {"sid": "a", "engine": "solo", "routing": "none", "effort": "high",
      "model": "opus-5", "worker": "solo", "fanout": 0, "n_turns": 10, "touches": 2,
      "cache_r": 0, "in_tok": 0, "cache_w": 0, "born": 2048, "killed": 0, "dollars": 10.0}
SB = {"sid": "b", "engine": "workflow", "routing": "cross-family", "effort": "low",
      "model": "sonnet-5", "worker": "haiku-4-5", "fanout": 8, "n_turns": 40, "touches": 5,
      "cache_r": 900, "in_tok": 100, "cache_w": 0, "born": 1024, "killed": 0, "dollars": 6.0}

VA = sf.features(SA)
VB = sf.features(SB)

# 2x2 codebook: node (0,0)=VA, (1,1)=VB, off-diagonal far away -> exact BMU assignment
CODEBOOK = {"schema": "vibrant/som-codebook@1", "version": "tv1",
            "lattice": {"rows": 2, "cols": 2}, "names": sf.FEATURE_NAMES,
            "codebook": [[VA, [0.0] * 18], [[1.0] * 18, VB]]}


def _sess(base, day, dollars, born):
    m = dict(base)
    m["day"] = day
    m["dollars"] = dollars
    m["born"] = born
    return m


def test_names_mismatch_rejected(fails):
    bad = dict(CODEBOOK, names=["x"] * 18)
    raised = False
    try:
        cm.build([_sess(SA, "2026-08-14", 10.0, 2048)], bad, "opZ")
    except (ValueError, Exception):
        raised = True
    check(raised, "names mismatch not rejected", fails)


def test_aggregation_and_window(fails):
    sessions = [
        _sess(SA, "2026-08-14", 10.0, 2048),   # -> (0,0) surv 2.0
        _sess(SA, "2026-08-13", 20.0, 2048),   # -> (0,0) surv 2.0
        _sess(SB, "2026-08-12", 6.0, 1024),    # -> (1,1) surv 1.0
        _sess(SA, "2026-06-01", 99.0, 4096),   # old, dropped by 14d window
    ]
    c = cm.build(sessions, CODEBOOK, "opZ", window_days=14)
    check(c["op"] == "opZ", "op not stamped", fails)
    check(c["codebook_version"] == "tv1", "version not stamped", fails)
    check(c["lattice"] == {"rows": 2, "cols": 2}, "lattice wrong", fails)
    # cell (0,0): two SA sessions in window: cost 30, surv 4.0, support 2
    check(c["cost"][0][0] == 30.0, f"cost[0][0] {c['cost'][0][0]}", fails)
    check(c["surv"][0][0] == 4.0, f"surv[0][0] {c['surv'][0][0]}", fails)
    check(c["support"][0][0] == 2, f"support[0][0] {c['support'][0][0]}", fails)
    # cell (1,1): SB: cost 6, surv 1.0, support 1
    check(c["cost"][1][1] == 6.0, f"cost[1][1] {c['cost'][1][1]}", fails)
    check(c["surv"][1][1] == 1.0, f"surv[1][1] {c['surv'][1][1]}", fails)
    check(c["support"][1][1] == 1, f"support[1][1] {c['support'][1][1]}", fails)
    # empty off-diagonal cells: null / 0
    check(c["cost"][0][1] is None and c["support"][0][1] == 0, "empty cell not null/0", fails)
    check(c["support"][1][0] == 0, "old-only cell has support (window failed)", fails)


def test_output_is_valid_and_clean(fails):
    c = cm.build([_sess(SA, "2026-08-14", 10.0, 2048)], CODEBOOK, "opZ")
    check(smg.validate_contribution(c) == [], f"produced contribution invalid: {smg.validate_contribution(c)}", fails)
    check(set(c.keys()) == {"schema", "op", "codebook_version", "lattice", "cost", "surv", "support"},
          f"leaked keys: {sorted(c.keys())}", fails)


def test_determinism(fails):
    ss = [_sess(SA, "2026-08-14", 10.0, 2048), _sess(SB, "2026-08-14", 6.0, 1024)]
    check(cm.build(ss, CODEBOOK, "opZ") == cm.build(ss, CODEBOOK, "opZ"),
          "build not deterministic", fails)


def main():
    fails = []
    for t in (test_names_mismatch_rejected, test_aggregation_and_window,
              test_output_is_valid_and_clean, test_determinism):
        t(fails)
    if fails:
        print("FAIL  contribute_map:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  contribute_map: shared-frame assignment, windowed aggregation, "
          "valid clean contribution, determinism")
    return 0


if __name__ == "__main__":
    sys.exit(main())
