#!/usr/bin/env python3
"""
Acceptance test for the driver-side SOM consumption (som_consume.spec.md):
load_som, som_map, and rig_space wiring.

The spec made executable, with hand-computed field and gradient answers.
Run: python3 test_som_consume.py   (exit 0 pass, 1 fail)
Stdlib only.
"""
import json
import os
import sys
import tempfile

import vibrant_report as vr


def check(cond, msg, fails):
    if not cond:
        fails.append(msg)


def _m(sid, day, cell, model, born, dollars, killed=0):
    """A per-session metric dict with all fields vector() reads. `cell` is only
    for building the matching cache entry; som_map reads the cell from the cache."""
    return {
        "sid": sid, "day": day, "engine": "solo", "model": model,
        "worker": "solo", "effort": "unknown",
        "born": born, "killed": killed, "out_tok": 1000, "dollars": dollars,
        "cache_r": 0, "in_tok": 0, "cache_w": 0, "orch_out": 500, "touches": 1,
        "_cell": cell,
    }


# six joined sessions; s_old is out of the field window but on the trajectory.
METRICS = [
    _m("s_old", "2026-06-01", [1, 1], "opus-4-8", 1024, 100.0),
    _m("sA", "2026-08-10", [0, 0], "opus-4-8", 2048, 10.0),
    _m("sB", "2026-08-11", [0, 0], "opus-4-8", 2048, 20.0),
    _m("sC", "2026-08-12", [2, 2], "sonnet-5", 2048, 5.0),
    _m("sD", "2026-08-13", [2, 2], "sonnet-5", 4096, 5.0),
    _m("sE", "2026-08-14", [0, 0], "opus-4-8", 1024, 6.0),
]

MOVE = {"axis": "orchestrator", "from": "opus-4-8", "to": "sonnet-5"}


def _cache(metrics, rows=4, cols=4):
    return {
        "schema": "vibrant/som@1",
        "feature_schema": "vibrant/session-features@1",
        "names": [f"f{i}" for i in range(18)],
        "lattice": {"rows": rows, "cols": cols},
        "sessions": [{"sid": m["sid"], "day": m["day"], "bmu": m["_cell"], "qe": 0.1}
                     for m in metrics],
    }


def test_load_som(fails):
    with tempfile.TemporaryDirectory() as d:
        # missing -> {}
        check(vr.load_som(d) == {}, "missing cache not {}", fails)
        # good
        p = os.path.join(d, "som-cache.json")
        with open(p, "w") as f:
            json.dump(_cache(METRICS), f)
        got = vr.load_som(d)
        check(got.get("schema") == "vibrant/som@1", "good cache not loaded", fails)
        # bad schema -> {}
        with open(p, "w") as f:
            json.dump({"schema": "nope"}, f)
        check(vr.load_som(d) == {}, "bad schema not rejected", fails)
        # corrupt -> {}
        with open(p, "w") as f:
            f.write("{not json")
        check(vr.load_som(d) == {}, "corrupt cache not rejected", fails)


def test_none_when_empty(fails):
    check(vr.som_map(METRICS, {}, MOVE) is None, "empty cache not None", fails)
    check(vr.som_map([], _cache(METRICS), MOVE) is None, "no join not None", fails)


def test_map_structure(fails):
    blk = vr.som_map(METRICS, _cache(METRICS), MOVE, field_window_days=14)
    check(blk is not None, "block is None", fails)
    if blk is None:
        return
    check(blk["lattice"] == {"rows": 4, "cols": 4}, f"lattice {blk['lattice']}", fails)
    check(blk["sessions_mapped"] == 6, f"mapped {blk['sessions_mapped']}", fails)
    check(blk["source"] == "learned", "source", fails)
    check(blk["field_metric"] == "d_per_survkb", "field_metric", fails)
    check(blk["field_lower_is_better"] is True, "lower_is_better", fails)
    check(blk["field_window_days"] == 14, "window", fails)


def test_trajectory_and_current(fails):
    blk = vr.som_map(METRICS, _cache(METRICS), MOVE)
    traj = blk["trajectory"]
    check(len(traj) == 6, f"traj len {len(traj)}", fails)
    check(traj[0]["cell"] == [1, 1] and traj[0]["day"] == "2026-06-01",
          f"traj head {traj[0]}", fails)
    check(traj[-1]["cell"] == [0, 0] and traj[-1]["day"] == "2026-08-14",
          f"traj tail {traj[-1]}", fails)
    check(blk["current_cell"] == [0, 0], f"current {blk['current_cell']}", fails)


def test_field_and_window(fails):
    blk = vr.som_map(METRICS, _cache(METRICS), MOVE, field_window_days=14)
    field, support = blk["field"], blk["support"]
    # cell (0,0): sA+sB+sE in window: dollars 36, survkb (2048+2048+1024)/1024=5.0 -> 7.2
    check(field[0][0] == 7.2, f"field[0][0] {field[0][0]}", fails)
    check(support[0][0] == 3, f"support[0][0] {support[0][0]}", fails)
    # cell (2,2): sC+sD: dollars 10, survkb (2048+4096)/1024=6.0 -> 1.6667
    check(field[2][2] == round(10.0 / 6.0, 4), f"field[2][2] {field[2][2]}", fails)
    check(support[2][2] == 2, f"support[2][2] {support[2][2]}", fails)
    # cell (1,1): only s_old, out of window -> null, support 0
    check(field[1][1] is None, f"field[1][1] {field[1][1]} (window failed)", fails)
    check(support[1][1] == 0, f"support[1][1] {support[1][1]}", fails)
    # an empty cell
    check(field[3][3] is None and support[3][3] == 0, "empty cell not null", fails)


def test_gradient(fails):
    blk = vr.som_map(METRICS, _cache(METRICS), MOVE)
    g = blk["gradient"]
    check(g["arm_change"] == MOVE, "arm_change not carried", fails)
    check(g["target_cell"] == [2, 2], f"target {g['target_cell']}", fails)
    check(g["vector"] == [2, 2], f"vector {g['vector']}", fails)  # (2,2)-(0,0)
    check(g["grounded_in"] == 2, f"grounded {g['grounded_in']}", fails)


def test_gradient_edge_cases(fails):
    # no move -> no arrow, arm_change null
    blk = vr.som_map(METRICS, _cache(METRICS), None)
    g = blk["gradient"]
    check(g["arm_change"] is None and g["target_cell"] is None and g["grounded_in"] == 0,
          f"none-move gradient {g}", fails)
    # move to an arm value no session has -> no arrow
    blk2 = vr.som_map(METRICS, _cache(METRICS),
                      {"axis": "orchestrator", "from": "opus-4-8", "to": "opus-5"})
    g2 = blk2["gradient"]
    check(g2["target_cell"] is None and g2["grounded_in"] == 0,
          f"unmatched-arm gradient {g2}", fails)


def test_undated_dropped(fails):
    extra = METRICS + [_m("s_undated", None, [3, 3], "opus-4-8", 2048, 1.0)]
    cache = _cache(extra)
    blk = vr.som_map(extra, cache, MOVE)
    check(blk["sessions_mapped"] == 6, f"undated not dropped: {blk['sessions_mapped']}", fails)


def test_determinism(fails):
    a = json.dumps(vr.som_map(METRICS, _cache(METRICS), MOVE), sort_keys=True)
    b = json.dumps(vr.som_map(METRICS, _cache(METRICS), MOVE), sort_keys=True)
    check(a == b, "som_map not deterministic", fails)


def main():
    fails = []
    for t in (test_load_som, test_none_when_empty, test_map_structure,
              test_trajectory_and_current, test_field_and_window, test_gradient,
              test_gradient_edge_cases, test_undated_dropped, test_determinism):
        t(fails)
    if fails:
        print("FAIL  som_consume:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  som_consume: load, join, trajectory, windowed field, arm-change arrow")
    return 0


if __name__ == "__main__":
    sys.exit(main())
