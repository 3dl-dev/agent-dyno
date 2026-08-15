#!/usr/bin/env python3
"""
Acceptance test for render_shared_map (item C): the federated shared-frontier render.

Structural, like test_som_viz; the real acceptance is a rendered screenshot. Confirms
the shared map reuses the SOM drawing with its own title and legend, draws your cell
and the frontier arrow, and stays self-contained.

Run: python3 test_shared_map.py   (exit 0 pass, 1 fail)
Stdlib only.
"""
import sys

import vibrant_report as vr


def check(cond, msg, fails):
    if not cond:
        fails.append(msg)


MERGED = {
    "schema": "vibrant/som-merged@1", "codebook_version": "v1",
    "lattice": {"rows": 3, "cols": 3},
    "field_metric": "d_per_survkb", "field_lower_is_better": True,
    "operators": ["opA", "opB"],
    "field": [[7.2, None, None], [None, 3.0, None], [None, None, 1.5]],
    "weight": [[10.0, 0, 0], [0, 4.0, 0], [0, 0, 6.0]],
    "support": [[3, 0, 0], [0, 2, 0], [0, 0, 4]],
    "contributors": [[2, 0, 0], [0, 1, 0], [0, 0, 2]],
    "spread": [[1.1, None, None], [None, None, None], [None, None, 0.5]],
}
CURRENT = [0, 0]
GRAD = {"target_cell": [2, 2], "vector": [2, 2], "support": 4, "weight": 6.0,
        "contributors": 2, "delta": 5.7}


def test_empty(fails):
    check(vr.render_shared_map(None, CURRENT, GRAD) == "", "None merged not empty", fails)
    check(vr.render_shared_map({"lattice": {}}, CURRENT, GRAD) == "", "no-lattice not empty", fails)


def test_load_shared_map(fails):
    import json
    import os
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        check(vr.load_shared_map(d) == {}, "missing shared map not {}", fails)
        p = os.path.join(d, "shared-map.json")
        with open(p, "w") as f:
            json.dump(MERGED, f)
        got = vr.load_shared_map(d)
        check(got.get("schema") == "vibrant/som-merged@1", "good shared map not loaded", fails)
        with open(p, "w") as f:
            json.dump({"schema": "nope"}, f)
        check(vr.load_shared_map(d) == {}, "bad schema not rejected", fails)
        with open(p, "w") as f:
            f.write("{not json")
        check(vr.load_shared_map(d) == {}, "corrupt not rejected", fails)


def test_structure(fails):
    out = vr.render_shared_map(MERGED, CURRENT, GRAD)
    check("<svg" in out, "no svg", fails)
    check(out.count("som-cell") == 9, f"cell count {out.count('som-cell')}", fails)
    check("som-current" in out, "no current marker", fails)
    check("som-arrow" in out, "no frontier arrow", fails)
    check("shared frontier" in out.lower(), "no shared-frontier title", fails)
    check("peer sessions" in out, "no peer-support caption", fails)


def test_no_external_refs(fails):
    out = vr.render_shared_map(MERGED, CURRENT, GRAD)
    for bad in ("http://", "https://", "url("):
        check(bad not in out, f"external ref {bad!r}", fails)


def test_no_arrow_without_target(fails):
    out = vr.render_shared_map(MERGED, CURRENT,
                               {"target_cell": None, "vector": None})
    check("som-arrow" not in out, "arrow drawn without target", fails)
    check(out.count("som-cell") == 9, "cells missing", fails)


def test_determinism(fails):
    check(vr.render_shared_map(MERGED, CURRENT, GRAD) ==
          vr.render_shared_map(MERGED, CURRENT, GRAD), "not deterministic", fails)


def main():
    fails = []
    for t in (test_empty, test_load_shared_map, test_structure, test_no_external_refs,
              test_no_arrow_without_target, test_determinism):
        t(fails)
    if fails:
        print("FAIL  shared_map:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  shared_map: shared-frontier reuse, your cell, frontier arrow, "
          "self-contained, determinism")
    return 0


if __name__ == "__main__":
    sys.exit(main())
