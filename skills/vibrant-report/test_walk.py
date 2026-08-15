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
    check("__CELLS__" not in out and "__BEST__" not in out and "__PERIODS__" not in out
          and "__CUR__" not in out and "__AGG__" not in out, "placeholders not filled", fails)
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


def test_recommend_ignores_noise(fails):
    # Regression: a 2-session cell with no flow data must not be recommended just
    # because it maxes the two dimensions it happens to have. Full coverage +
    # support weighting should prefer a proven, fully-measured cell instead.
    cells = [
        # metric-maxing outlier: highest eff and simp, but only 2 sessions and NO flow
        {"r": 0, "c": 0, "eff": 18.3, "flow": None, "simp": 96.0, "sessions": 2},
        # solid, fully measured, well supported
        {"r": 1, "c": 1, "eff": 6.15, "flow": 64.0, "simp": 64.3, "sessions": 12},
        {"r": 2, "c": 2, "eff": 5.75, "flow": 48.0, "simp": 88.5, "sessions": 11},
    ]
    rec = vr._recommend_cells(cells, current_cell=[2, 2])
    bal = rec["eff,flow,simp"]["cell"]
    check(bal != [0, 0], "balanced objective still picks the flow-less 2-session outlier", fails)
    # whatever it picks for balance must actually have all three dimensions measured
    chosen = next((c for c in cells if [c["r"], c["c"]] == bal), None)
    check(chosen is not None
          and chosen["eff"] is not None and chosen["flow"] is not None
          and chosen["simp"] is not None,
          "balanced recommendation is not a full-coverage cell", fails)
    # a <2-session cell is never eligible
    edge = vr._recommend_cells([{"r": 0, "c": 0, "eff": 9.0, "flow": 90.0,
                                 "simp": 90.0, "sessions": 1}], current_cell=[0, 0])
    check(all(v["cell"] is None and not v["ok"] for v in edge.values()),
          "1-session cell was recommended", fails)


def test_recommend_noise_gate(fails):
    # The gate works on the NORMALIZED field: a move whose objective gain over the
    # current cell is small relative to the spread of your cells (scaled up by thin
    # support) must NOT be surfaced as a call to action (ok False). 'cell' (the argmax,
    # used by the scrub) is still reported; only 'ok' differs.
    # A field where current is already near the top and the best is only slightly above.
    spread = [
        {"r": 3, "c": 3, "eff": 2.0, "flow": 20.0, "simp": 20.0, "sessions": 20},
        {"r": 4, "c": 4, "eff": 3.0, "flow": 30.0, "simp": 30.0, "sessions": 20},
        {"r": 5, "c": 5, "eff": 5.0, "flow": 50.0, "simp": 50.0, "sessions": 20},
    ]
    marginal = spread + [
        {"r": 0, "c": 0, "eff": 8.0, "flow": 80.0, "simp": 80.0, "sessions": 30},  # current, near top
        {"r": 1, "c": 1, "eff": 8.5, "flow": 82.0, "simp": 82.0, "sessions": 25},  # barely above
    ]
    r = vr._recommend_cells(marginal, current_cell=[0, 0])["eff,flow,simp"]
    check(r["cell"] is not None, "argmax cell should still be reported for the scrub", fails)
    check(r["ok"] is False, "a gain small against the field's spread was surfaced as a move", fails)
    # a decisive, well-supported gain (current poor, best far above) clears the gate.
    decisive = spread + [
        {"r": 0, "c": 0, "eff": 2.0, "flow": 20.0, "simp": 20.0, "sessions": 30},  # current, poor
        {"r": 1, "c": 1, "eff": 9.0, "flow": 90.0, "simp": 90.0, "sessions": 30},  # clearly better
    ]
    r2 = vr._recommend_cells(decisive, current_cell=[0, 0])["eff,flow,simp"]
    check(r2["cell"] == [1, 1] and r2["ok"] is True,
          "a decisive, well-supported gain was gated out", fails)
    # standing on the best cell is a hold, not a self-referential recommendation.
    r3 = vr._recommend_cells(decisive, current_cell=[1, 1])["eff,flow,simp"]
    check(r3["ok"] is False, "recommended a move to the cell you are already on", fails)


def test_rank_opacity_spreads(fails):
    # The dynamic shade ranks values, so a clumped-cheap distribution with one costly
    # outlier does NOT collapse the cheap cluster onto the floor (the washout a fixed
    # log ramp produced). Cheap cells share a mid-low shade; mids and the outlier spread.
    vals = [1.0, 1.0, 1.0, 1.0, 2.0, 3.0, 50.0]
    sv = sorted(vals)
    ops = [vr._rank_opacity(v, sv, True) for v in vals]
    check(len(set(round(o, 3) for o in ops)) >= 4, "rank opacity does not spread distinct values", fails)
    check(vr._rank_opacity(1.0, sv, True) > 0.20, "cheap cluster slammed to the floor (washout)", fails)
    check(vr._rank_opacity(1.0, sv, True) < vr._rank_opacity(50.0, sv, True),
          "rank opacity not monotone in cost when lower_better", fails)
    check(vr._rank_opacity(1.0, sv, False) > vr._rank_opacity(50.0, sv, False),
          "lower_better=False did not invert the shade", fails)
    check(vr._rank_opacity(5.0, [5.0], True) == 0.5, "single-value cell not neutral", fails)


def _era_report():
    days = ["2026-08-0%d" % d for d in range(1, 7)]  # six consecutive days
    labels = [vr._bucket(d, "day")[1] for d in days]
    timeline = [{"week": labels[i], "eq": 5.0, "misery": 40.0, "shipped": 10.0,
                 "complexity": 100.0,
                 "changes": (["engine solo -> workflow"] if i == 3 else None)}
                for i in range(6)]
    walk = []
    for i, d in enumerate(days):
        if i < 3:  # era 0: prevailingly cell [0,0], with a one-off flicker to [1,1]
            walk += [{"day": d, "cell": [0, 0]}, {"day": d, "cell": [0, 0]}]
            if i == 1:
                walk.append({"day": d, "cell": [1, 1]})
        else:      # era 1: prevailingly cell [2,2], with a one-off flicker back to [0,0]
            walk += [{"day": d, "cell": [2, 2]}, {"day": d, "cell": [2, 2]}]
            if i == 4:
                walk.append({"day": d, "cell": [0, 0]})
    return {"fuel_and_work": {"granularity": "day"}, "timeline": timeline,
            "rig_space": {"som": {"walk": walk, "current_cell": [2, 2]}}}


def test_timeline_periods_era_smoothed(fails):
    # The map moves per ERA, not per noisy bucket: within a stable era the prevailing
    # cell is held despite day-to-day flicker; it changes only at the detected boundary.
    rep = _era_report()
    p = vr._timeline_periods(rep)
    check(len(p) == 6, "expected six periods", fails)
    distinct = {tuple(x["cell"]) for x in p}
    check(distinct == {(0, 0), (2, 2)}, "flicker not smoothed to prevailing cells: %s" % distinct, fails)
    check([x["cell"] for x in p[:3]] == [[0, 0]] * 3, "era 0 not held at its prevailing cell", fails)
    check([x["cell"] for x in p[3:]] == [[2, 2]] * 3, "era 1 not held at its prevailing cell", fails)
    check([x["era"] for x in p] == [0, 0, 0, 1, 1, 1], "era ids not segmented at the change", fails)
    # exactly one real move (at the boundary), not five noisy hops.
    moves = sum(1 for a, b in zip(p, p[1:]) if a["cell"] != b["cell"])
    check(moves == 1, "expected one era transition, got %d" % moves, fails)
    # the card's baseline sits on the latest era's prevailing style.
    check(vr._prevailing_current(rep) == [2, 2], "prevailing-current not the latest era's cell", fails)


def test_determinism(fails):
    check(vr.render_walk(REPORT) == vr.render_walk(REPORT), "render_walk not deterministic", fails)


def main():
    fails = []
    for t in (test_empty, test_script, test_no_external_refs, test_no_em_dash,
              test_card_maps_interactive, test_hero_toggles, test_recommend_ignores_noise,
              test_recommend_noise_gate, test_rank_opacity_spreads,
              test_timeline_periods_era_smoothed, test_determinism):
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
