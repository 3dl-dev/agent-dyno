#!/usr/bin/env python3
"""
Acceptance test for the in-card interactivity: render_walk (the driving script) and
_card_maps (the interactive fingerprint in the card).

Structural; the real proof is the rendered, interactive page. This guards the
plumbing: the card map is queryable and JS-drivable, the script embeds the per-cell
metrics / per-period series / aggregate, the objective+toggle hooks are present, and
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
         "effort": "high", "sessions": 3, "cost": 7.2, "eff": 4.5, "flow": 60.0,
         "simp": 40.0},
        {"cell": [2, 2], "engine": "workflow", "model": "sonnet-5", "worker": "haiku-4-5",
         "effort": "low", "sessions": 2, "cost": 1.5, "eff": 8.0, "flow": 70.0,
         "simp": 55.0}],
    "walk": [
        {"day": "2026-08-10", "cell": [0, 0], "flow": 80.0, "cost": 7.2},
        {"day": "2026-08-12", "cell": [2, 2], "flow": None, "cost": 1.5}],
}
REPORT = {"rig_space": {"som": SOM}, "shared_map": None,
          "topline": {"eq": 8.0, "simplicity": 55.0}, "misery": {"flow": 60.0},
          "timeline": []}


def check(cond, msg, fails):
    if not cond:
        fails.append(msg)


def test_empty(fails):
    check(vr.render_walk({}) == "", "empty report not ''", fails)
    check(vr.render_walk({"rig_space": {"som": {"walk": []}}}) == "", "no-walk not ''", fails)


def test_script(fails):
    out = vr.render_walk(REPORT)
    check("<script>" in out, "no driving script", fails)
    # data embedded (placeholders substituted)
    check("__CELLS__" not in out and "__PERIODS__" not in out and "__CUR__" not in out
          and "__AGG__" not in out, "placeholders not filled", fails)
    check('"simp":' in out or "simp" in out, "per-cell metrics not embedded", fails)
    # references the card elements it drives
    for hook in ("map-you", "wv-bar", "vb-score", "mtog", "vb-rec"):
        check(hook in out, f"script does not reference {hook}", fails)


def test_no_external_refs(fails):
    out = vr.render_walk(REPORT).replace("http://www.w3.org/2000/svg", "")
    for bad in ("http://", "https://", "url(http", "url(//", "src="):
        check(bad not in out, f"external ref {bad!r}", fails)


def test_no_em_dash(fails):
    check("\u2014" not in (vr.render_walk(REPORT) + vr._card_maps(REPORT)),
          "em-dash in output", fails)


def test_card_maps_interactive(fails):
    row = vr._card_maps(REPORT)
    check("som-maps-row" in row, "no maps row", fails)
    check('id="map-you"' in row, "card map not interactive (no map-you id)", fails)
    check('data-r="2" data-c="2"' in row, "card cells not queryable", fails)
    check("som-fx" in row, "no JS-owned effects group (markers + arrow) in card map", fails)
    check('id="vb-rec"' in row, "no recommendation slot below the fingerprints", fails)
    check('id="vb-detail"' in row, "no separate description/detail slot", fails)
    check("Where you work" in row, "personal fingerprint missing", fails)


def test_hero_toggles(fails):
    rep = dict(REPORT, misery={"flow": 60.0, "overall": 40.0})
    card = vr._hero_card(rep)
    check('id="vb-score"' in card, "no score element", fails)
    check('class="mtog" data-m="eff"' in card, "efficiency not a toggle", fails)
    check('data-m="flow"' in card and 'data-m="simp"' in card, "flow/simp not toggles", fails)
    check("obj-chip" not in card, "duplicate objective chips still present", fails)


def test_determinism(fails):
    check(vr.render_walk(REPORT) == vr.render_walk(REPORT), "render_walk not deterministic", fails)


def main():
    fails = []
    for t in (test_empty, test_script, test_no_external_refs, test_no_em_dash,
              test_card_maps_interactive, test_hero_toggles, test_determinism):
        t(fails)
    if fails:
        print("FAIL  walk:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  walk: in-card interactive map, embedded data, toggle+scrub hooks, "
          "recommendation slot, self-contained, determinism")
    return 0


if __name__ == "__main__":
    sys.exit(main())
