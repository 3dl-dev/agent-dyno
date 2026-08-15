#!/usr/bin/env python3
"""
Acceptance test for the misery layer (the second meter), the spec made executable.

Misery is efficiency's twin: a meter over the SAME fingerprint parameter space,
sliced by every arm, never folded into EQ, and operator-relative. This test drives
the driver-side (deterministic) consumption of a misery cache with synthetic
sessions of known scores + fingerprints, and asserts the contract in misery.spec.md.
The inference cascade that WRITES the cache lives in the skill and is not tested here
(it is not deterministic); the driver's consumption of the cache is.

    python3 skills/vibrant-report/test_misery.py     # exits 0 on pass, 1 on fail
Stdlib only.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vibrant_report as vr  # noqa: E402


def synth(sid, model, worker, engine, effort, misery, out=1_000_000):
    """A per-session metric dict with a fingerprint and a misery score."""
    return {"sid": sid, "day": "2026-08-10", "proj": "repo", "engine": engine,
            "routing": "none", "model": model, "worker": worker,
            "model_roles": f"{model} -> {worker}", "effort": effort,
            "born": 2048, "killed": 0, "out_tok": out, "in_tok": 0, "cache_r": 0,
            "cache_w": 0, "orch_out": 0, "touches": 0, "nudges": 0, "interrupts": 0,
            "ends_q": 0, "n_turns": 10, "fanout": 0, "dollars": 1.0, "misery": misery}


def main():
    fails = []

    # ---- (1) cache load: schema + absent -> {} ----
    with tempfile.TemporaryDirectory() as d:
        json.dump({"schema": "vibrant/misery@1",
                   "sessions": {"s1": {"score": 40, "tags": ["frustration"],
                                       "evidence": "ugh"}}},
                  open(os.path.join(d, "misery-cache.json"), "w"))
        if vr.load_misery(d).get("s1", {}).get("score") != 40:
            fails.append("load_misery did not read the cached score")
    if vr.load_misery("/nonexistent/dir") != {}:
        fails.append("an absent misery cache must load as {} (no-misery run)")

    # ---- (2) misery is a function of the fingerprint: hold the MODEL fixed, and
    # topology alone must swing it (the 'wrong fingerprint, not the model' invariant) ----
    metrics = [
        synth("a", "opus-4-8", "solo", "solo", "high", 20),
        synth("b", "opus-4-8", "solo", "solo", "high", 24),
        synth("c", "opus-4-8", "opus-5", "workflow", "high", 60),
        synth("d", "opus-4-8", "opus-5", "workflow", "high", 64),
        synth("e", "opus-5", "solo", "solo", "high", 50),
    ]
    o48 = [m for m in metrics if m["model"] == "opus-4-8"]
    solo = vr._misery_by(o48, "engine").get("solo")
    wf = vr._misery_by(o48, "engine").get("workflow")
    if not (solo == 22.0 and wf == 62.0 and wf > solo):
        fails.append(f"holding model=opus-4-8, topology must swing misery "
                     f"(solo {solo} vs workflow {wf})")

    # ---- (3) sliced by every arm, and per-rig ----
    for dim in ("model", "worker", "model_roles", "effort", "engine", "routing"):
        if not vr._misery_by(metrics, dim):
            fails.append(f"misery not sliced by '{dim}'")
    roles = vr._misery_by(metrics, "model_roles")
    if roles.get("opus-4-8 -> solo") != 22.0 or "opus-4-8 -> opus-5" not in roles:
        fails.append(f"per-rig misery wrong: {roles}")

    # ---- (4) per-era / per-bucket misery on the timeline ----
    tl = vr.timeline(metrics, gran="day")
    if not tl or any(r.get("misery") is None for r in tl):
        fails.append("timeline buckets carry no misery")

    # ---- (5) NEVER folded into EQ: clearing misery must not move the topline ----
    num = {"durable_complexity": 100, "net_complexity": 100, "change_failure_rate": 0}
    eq_with = vr.topline(metrics, num)["eq"]
    for m in metrics:
        m["misery"] = None
    eq_without = vr.topline(metrics, num)["eq"]
    if eq_with != eq_without:
        fails.append(f"misery leaked into EQ: {eq_with} != {eq_without}")
    for m, sc in zip(metrics, (20, 24, 60, 64, 50)):
        m["misery"] = sc  # restore

    # ---- (6) render: the card, the surface, and the by-rig table carry misery ----
    scored = [m for m in metrics if m["misery"] is not None]
    overall = round(sum(m["misery"] for m in scored) / len(scored), 1)
    report = {
        "topline": {"eq": 20.0, "sessions": 5, "change_failure_rate": 0},
        "misery": {"overall": overall, "n_scored": len(scored),
                   "by_model_roles": roles, "by_engine": vr._misery_by(metrics, "engine")},
        "fingerprint": {}, "timeline": tl,
        "numerator": {"attribution": {"matched": 1, "by_model_roles": {
            "opus-4-8 -> solo": {"surviving": 10, "net_complexity": 5, "commits": 2}}}},
    }
    flow = round(100 - overall, 1)
    card = vr._hero_card(report)
    if "flow" not in card or f">{flow:g}</b> flow" not in card:
        fails.append("card is missing the flow component")
    md = vr.render_md(report)
    if f"Flow {flow}/100" not in md or "never folded into efficiency" not in md:
        fails.append("report.md is missing the flow meter / its 'not folded' caveat")
    tbl = vr.render_attribution(report)
    if "<th>misery</th>" not in tbl or ">22.0<" not in tbl:
        fails.append("the by-rig table is missing the misery column")

    # ---- (7) governance + determinism ----
    if "person" in md.lower() and "vs" in md.lower():
        fails.append("misery surface leaked a person-vs-person comparison")
    if vr.render_md(report) != md or vr._hero_card(report) != card:
        fails.append("misery render is not deterministic")

    # ---- (8) no-cache run: a report with misery None renders clean, no crash ----
    nomis = dict(report, misery=None)
    _ = vr.render_md(nomis)
    c2 = vr._hero_card(nomis)
    if "misery" in c2:
        fails.append("a no-misery run still rendered the misery meter")

    if fails:
        print("FAIL  misery:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  misery: cache, fingerprint-function, slices, no-fold, render, determinism")
    return 0


if __name__ == "__main__":
    sys.exit(main())
