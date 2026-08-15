#!/usr/bin/env python3
"""
Acceptance test for the interactive walk (render_walk) and the card marquee
(_card_maps). Structural: the real proof is the rendered, interactive page (drive
the slider and hover). This guards the plumbing: the map has queryable cells, the
walk and per-cell meaning are embedded, the scrubber and detail panel exist, and
nothing reaches the network.

Run: python3 test_walk.py   (exit 0 pass, 1 fail)
Stdlib only.
"""
import sys

import vibrant_report as vr

SOM = {
    "source": "learned", "lattice": {"rows": 3, "cols": 3},
    "sessions_mapped": 3, "current_cell": [2, 2],
    "field_metric": "d_per_survkb", "field_lower_is_better": True,
    "field_window_days": 14,
    "field": [[7.2, None, None], [None, 3.0, None], [None, None, 1.5]],
    "support": [[3, 0, 0], [0, 1, 0], [0, 0, 2]],
    "drift": [{"day": "2026-08-10", "pos": [0.0, 0.0]}],
    "gradient": {"arm_change": {"tweak": "Try sonnet-5."}, "target_cell": [1, 1],
                 "vector": [-1, -1]},
    "cell_meaning": [
        {"cell": [0, 0], "engine": "solo", "model": "opus-4-8", "worker": "solo",
         "effort": "high", "sessions": 3, "cost": 7.2},
        {"cell": [2, 2], "engine": "workflow", "model": "sonnet-5", "worker": "haiku-4-5",
         "effort": "low", "sessions": 2, "cost": 1.5}],
    "walk": [
        {"day": "2026-08-10", "cell": [0, 0], "flow": 80.0, "cost": 7.2,
         "engine": "solo", "model": "opus-4-8", "effort": "high"},
        {"day": "2026-08-12", "cell": [2, 2], "flow": None, "cost": 1.5,
         "engine": "workflow", "model": "sonnet-5", "effort": "low"}],
}
REPORT = {"rig_space": {"som": SOM}, "shared_map": None}


def check(cond, msg, fails):
    if not cond:
        fails.append(msg)


def test_empty(fails):
    check(vr.render_walk({}) == "", "empty report not ''", fails)
    check(vr.render_walk({"rig_space": {"som": {"walk": []}}}) == "", "no-walk not ''", fails)


def test_structure(fails):
    out = vr.render_walk(REPORT)
    check('id="map-you"' in out, "no map-you svg id", fails)
    check('data-r="2" data-c="2"' in out, "cells not queryable by data-r/data-c", fails)
    check("som-here" in out, "no scrubber marker", fails)
    check('id="walk-scrub"' in out and 'id="walk-detail"' in out, "no scrubber/detail", fails)
    check("<script>" in out, "no walk script", fails)
    # the walk and meaning are embedded (placeholders substituted)
    check("__WALK__" not in out and "__CM__" not in out, "placeholders not filled", fails)
    check('"cell":[2,2]' in out or '"cell": [2, 2]' in out or '[2,2]' in out,
          "walk data not embedded", fails)
    check('"engine":"workflow"' in out or "workflow" in out, "cell meaning not embedded", fails)


def test_no_external_refs(fails):
    out = vr.render_walk(REPORT)
    # internal url(#clip) fragment refs are fine; only external references are banned.
    for bad in ("http://", "https://", "url(http", "url(//", "src="):
        check(bad not in out, f"external ref {bad!r}", fails)


def test_no_em_dash(fails):
    # the interactive strings must not introduce an em-dash into the output
    check("\u2014" not in vr.render_walk(REPORT), "em-dash in walk output", fails)


def test_card_maps(fails):
    row = vr._card_maps(REPORT)
    check("som-maps-row" in row, "no maps row", fails)
    check(row.count("som-compact") >= 1, "no compact map on card", fails)
    check("Where you work" in row, "personal marquee missing", fails)


def test_determinism(fails):
    check(vr.render_walk(REPORT) == vr.render_walk(REPORT), "render_walk not deterministic", fails)


def main():
    fails = []
    for t in (test_empty, test_structure, test_no_external_refs, test_no_em_dash,
              test_card_maps, test_determinism):
        t(fails)
    if fails:
        print("FAIL  walk:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  walk: queryable cells, embedded walk + meaning, scrubber, marquee, "
          "self-contained, determinism")
    return 0


if __name__ == "__main__":
    sys.exit(main())
