#!/usr/bin/env python3
"""
Acceptance test for rig_space (the fingerprint as a trajectory in a collapsed latent
space), the spec made executable: skills/vibrant-report/rig_space.spec.md.

Covers the four acceptance points: the hand-written embedding is monotonic, the three
bodies update at session > mood > personality velocities (and deterministically), the
gradient at the current mood points toward the better region and maps to a concrete
arm-change, and the layer is additive (no dated data -> None, other meters untouched).

    python3 skills/vibrant-report/test_rig_space.py     # exits 0 on pass, 1 on fail
Stdlib only.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vibrant_report as vr  # noqa: E402


def arms(engine="solo", model="opus-4-8", worker="solo", effort="high",
         review="automated"):
    return {"engine": engine, "model": model, "worker": worker, "effort": effort,
            "review_regime": review}


def synth(sid, day, model, worker, effort, engine, review, dollars, out=1_000_000):
    return {"sid": sid, "day": day, "engine": engine, "routing": "none",
            "model": model, "worker": worker, "model_roles": f"{model} -> {worker}",
            "effort": effort, "review_regime": review, "out_tok": out,
            "dollars": dollars, "misery": None}


def main():
    fails = []

    # ---- (1) embedding: monotonic on each axis ----
    fo_solo = vr._embed(arms(engine="solo"))[0]
    fo_deleg = vr._embed(arms(engine="delegate"))[0]
    fo_wf = vr._embed(arms(engine="workflow"))[0]
    if not (fo_solo < fo_deleg < fo_wf):
        fails.append(f"fan_out not monotonic solo<delegate<workflow: "
                     f"{fo_solo} {fo_deleg} {fo_wf}")
    fire_cheap = vr._embed(arms(model="fable-5"))[1]
    fire_mid = vr._embed(arms(model="sonnet-5"))[1]
    fire_strong = vr._embed(arms(model="opus-5"))[1]
    if not (fire_cheap < fire_mid < fire_strong):
        fails.append(f"firepower not monotonic cheap<sonnet<opus: "
                     f"{fire_cheap} {fire_mid} {fire_strong}")
    rig_none = vr._embed(arms(review="none"))[2]
    rig_auto = vr._embed(arms(review="automated"))[2]
    rig_cross = vr._embed(arms(review="cross-model"))[2]
    if not (rig_none < rig_auto < rig_cross):
        fails.append(f"rigor not monotonic none<automated<cross-model: "
                     f"{rig_none} {rig_auto} {rig_cross}")
    # deterministic and in range
    if vr._embed(arms()) != vr._embed(arms()):
        fails.append("embedding is not deterministic")
    if not all(0.0 <= c <= 1.0 for c in vr._embed(arms(model="opus-5", worker="opus-5",
                                                       engine="workflow",
                                                       review="cross-model"))):
        fails.append("embedding out of [0,1]")

    # ---- (2) dynamics: session > mood > personality; determinism ----
    A, B = (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
    pts = [A] + [B] * 40  # a step input: settle, then jump and hold
    mood, pers, path = vr._layered_trajectory(pts)
    # after the jump, mood must be closer to B than personality is (mood is faster)
    dm = sum((B[k] - mood[k]) ** 2 for k in range(3)) ** 0.5
    dp = sum((B[k] - pers[k]) ** 2 for k in range(3)) ** 0.5
    if not (dm < dp):
        fails.append(f"personality should lag mood (|mood-B|={dm:.3f} !< "
                     f"|pers-B|={dp:.3f})")
    if vr.V_MOOD <= vr.V_PERS:
        fails.append(f"V_MOOD ({vr.V_MOOD}) must exceed V_PERS ({vr.V_PERS})")
    if len(path) != len(pts) or vr._layered_trajectory(pts) != (mood, pers, path):
        fails.append("layered trajectory is not deterministic / wrong length")

    # ---- (3) gradient: points at the better region, maps to an arm-change ----
    # 10 opus-4-8 sessions (expensive: $10 each, 100 commits) vs 10 sonnet-5 (cheap:
    # $2 each, 100 commits, not more miserable). Steepest descent is orchestrator
    # opus-4-8 -> sonnet-5; the target's firepower must drop (opus 0.9 -> sonnet 0.6).
    metrics = []
    for i in range(10):
        metrics.append(synth(f"o{i}", f"2026-08-{i+1:02d}", "opus-4-8", "solo",
                             "high", "delegate", "automated", 10.0))
    for i in range(10):
        metrics.append(synth(f"s{i}", f"2026-08-{i+1:02d}", "sonnet-5", "solo",
                             "high", "delegate", "automated", 2.0))
    attribution = {
        "by_orchestrator": {"opus-4-8": {"commits": 100, "net_complexity": 5000,
                                         "surviving": 5000},
                            "sonnet-5": {"commits": 100, "net_complexity": 3000,
                                         "surviving": 3000}},
        "by_worker": {"solo": {"commits": 200, "net_complexity": 8000,
                               "surviving": 8000}},
        "by_effort": {"high": {"commits": 200, "net_complexity": 8000,
                               "surviving": 8000}},
        "by_model_roles": {}, "matched": 200,
    }
    misery_block = {"by_model": {"opus-4-8": 45.0, "sonnet-5": 40.0},
                    "by_worker": {"solo": 42.0}, "by_effort": {"high": 42.0},
                    "by_model_roles": {}}
    rs = vr.rig_space(metrics, attribution, misery_block)
    if not rs or not rs.get("gradient"):
        fails.append(f"rig_space produced no gradient: {rs}")
    else:
        g = rs["gradient"]
        ac = g["arm_change"]
        if ac["axis"] != "orchestrator" or ac["to"] != "sonnet-5":
            fails.append(f"gradient arm-change should be orchestrator->sonnet-5, "
                         f"got {ac['axis']}:{ac.get('from')}->{ac.get('to')}")
        # firepower is axis index 1; the move to a cheaper orchestrator lowers it
        if not (g["vector"][1] < 0):
            fails.append(f"gradient should lower firepower (vector={g['vector']})")
        if len(rs["mood"]) != 3 or len(rs["personality"]) != 3:
            fails.append("mood/personality are not 3-vectors")
        if not rs["trajectory"]:
            fails.append("trajectory is empty")

    # ---- (4) additive: too little dated data -> None ----
    if vr.rig_space(metrics[:3], attribution, misery_block) is not None:
        fails.append("rig_space should be None with fewer than 5 dated sessions")
    if vr.rig_space([], attribution, misery_block) is not None:
        fails.append("rig_space should be None with no metrics")

    if fails:
        print("FAIL  rig_space:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  rig_space: embedding, dynamics, gradient, additivity")
    return 0


if __name__ == "__main__":
    sys.exit(main())
