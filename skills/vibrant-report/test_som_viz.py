#!/usr/bin/env python3
"""
Acceptance test for the SOM map render (som_viz.spec.md): render_som_map.

Structural only. The real acceptance is a rendered screenshot (see the spec);
this guards the plumbing: correct element counts, no external refs, determinism,
empty string when there is no SOM block.

Run: python3 test_som_viz.py   (exit 0 pass, 1 fail)
Stdlib only.
"""
import sys

import vibrant_report as vr


def check(cond, msg, fails):
    if not cond:
        fails.append(msg)


BLOCK = {
    "source": "learned",
    "lattice": {"rows": 3, "cols": 3},
    "sessions_mapped": 5,
    "trajectory": [{"day": "2026-08-10", "cell": [0, 0]},
                   {"day": "2026-08-11", "cell": [1, 1]},
                   {"day": "2026-08-12", "cell": [2, 2]}],
    "drift": [{"day": "2026-08-10", "pos": [0.0, 0.0]},
              {"day": "2026-08-11", "pos": [0.2, 0.2]},
              {"day": "2026-08-12", "pos": [0.56, 0.56]}],
    "current_cell": [2, 2],
    "field_metric": "d_per_survkb",
    "field_lower_is_better": True,
    "field_window_days": 14,
    "field": [[7.2, None, None], [None, 3.0, None], [None, None, 1.5]],
    "support": [[3, 0, 0], [0, 1, 0], [0, 0, 2]],
    "gradient": {"arm_change": {"axis": "orchestrator", "from": "opus-4-8",
                                "to": "sonnet-5"},
                 "target_cell": [2, 0], "vector": [0, -2], "grounded_in": 2},
}


def test_empty(fails):
    check(vr.render_som_map(None) == "", "None not empty string", fails)
    check(vr.render_som_map({}) == "", "{} not empty string", fails)


def test_structure(fails):
    out = vr.render_som_map(BLOCK)
    check("<svg" in out, "no svg", fails)
    check(out.count("som-cell") == 9, f"cell count {out.count('som-cell')} != 9", fails)
    check("som-current" in out, "no current marker", fails)
    check("som-key" in out, "no always-visible key", fails)
    check("you" in out and "cheaper" in out, "no on-figure you/cheaper labels", fails)
    check("som-current" in out, "no current marker", fails)
    check("som-arrow" in out, "no arrow (target_cell set)", fails)
    check("sonnet-5" in out, "arm-change caption missing 'to' value", fails)


def test_no_external_refs(fails):
    out = vr.render_som_map(BLOCK)
    for bad in ("http://", "https://", "url("):
        check(bad not in out, f"external ref {bad!r} in svg", fails)


def test_no_arrow_when_null_target(fails):
    blk = dict(BLOCK)
    blk["gradient"] = {"arm_change": None, "target_cell": None, "vector": None,
                       "grounded_in": 0}
    out = vr.render_som_map(blk)
    check("som-arrow" not in out, "arrow drawn with null target", fails)
    check(out.count("som-cell") == 9, "cells missing without arrow", fails)


def test_styles(fails):
    # classic keeps the red cost hue and rect cells
    classic = vr.render_som_map(BLOCK, style="classic")
    check("var(--down-rgb)" in classic and "<rect class=\"som-cell\"" in classic,
          "classic style not rect/red", fails)
    # ink: 3dl palette (ink cells, rust peak, teal arrow), still rect
    ink = vr.render_som_map(BLOCK, style="ink")
    check("var(--ink-rgb)" in ink, "ink cells not ink", fails)
    check("var(--rust)" in ink, "no rust peak (current cell)", fails)
    check("var(--teal)" in ink, "arrow not teal", fails)
    check("<rect class=\"som-cell\"" in ink, "ink not rect", fails)
    # ink-hex: hexagonal cells + the fingerprint ridge layer (oval clip + contour paths)
    hexed = vr.render_som_map(BLOCK, style="ink-hex")
    check("<polygon class=\"som-cell\"" in hexed, "ink-hex not hexagonal", fails)
    check(hexed.count("som-cell") == 9, f"hex cell count {hexed.count('som-cell')}", fails)
    check("var(--rust)" in hexed and "var(--teal)" in hexed, "hex missing rust/teal", fails)
    check("rgba(0,0,0,0)" in hexed, "hex grid not tapered into an oval", fails)


def test_waveform(fails):
    rep = {"topline": {"eq": 8.0, "simplicity": 60.0}, "misery": {"flow": 55.0},
           "timeline": [
               {"eq": 5.0, "misery": 40, "shipped": 10, "complexity": 300, "week": "w1"},
               {"eq": 8.0, "misery": 30, "shipped": 12, "complexity": 200, "week": "w2"},
               {"eq": 6.0, "misery": None, "shipped": 0, "complexity": 0, "week": "w3"},
               {"eq": 9.0, "misery": 20, "shipped": 15, "complexity": 250, "week": "w4"}]}
    out = vr.render_waveform(rep)
    check("<svg" in out, "no waveform svg", fails)
    for lab in ("combined", "efficiency", "flow", "simplicity"):
        check(lab in out, f"missing {lab} wave", fails)
    check(out.count("<rect") >= 4, f"too few wave bars: {out.count('<rect')}", fails)
    # gap-filled: the bucket with no misery/no shipped still contributes (overall fill)
    check(len(vr._combined_series(rep)) == 4, "combined series should gap-fill to 4", fails)
    check(vr.render_waveform({"topline": {"eq": 1}, "timeline": []}) == "",
          "empty timeline not ''", fails)
    check(vr.render_waveform(rep) == vr.render_waveform(rep), "waveform not deterministic", fails)
    # every style is deterministic
    for st in ("classic", "ink", "ink-hex"):
        check(vr.render_som_map(BLOCK, style=st) == vr.render_som_map(BLOCK, style=st),
              f"style {st} not deterministic", fails)


def test_determinism(fails):
    check(vr.render_som_map(BLOCK) == vr.render_som_map(BLOCK),
          "render not deterministic", fails)


def main():
    fails = []
    for t in (test_empty, test_structure, test_no_external_refs,
              test_no_arrow_when_null_target, test_styles, test_waveform,
              test_determinism):
        t(fails)
    if fails:
        print("FAIL  som_viz:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  som_viz: empty-guard, cell/path/current/arrow, no external refs, determinism")
    return 0


if __name__ == "__main__":
    sys.exit(main())
