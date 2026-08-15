#!/usr/bin/env python3
"""
session_features.py, per-session feature extractor for the learned SOM
(session_features.spec.md).

The SOM (som_train.py) learns a low-dimensional organization of the operator's
sessions from a feature vector per session. This is the grain change the
rig-space handoff calls for: the unit is a single session, not one of the
handful of rig-configs. It is the learned upgrade's front door; the driver's
hand-written `_embed` priors stay as the fallback.

The one load-bearing rule: the vector encodes a session's SHAPE, the
configuration arms the operator chose and the working-style topology those
choices produced. It never encodes the economic outcome (surviving work,
dollars, efficiency) or the operator's friction (misery, nudges, interrupts).
Those are the field painted over the learned map by the driver; the gradient
descends that field. Shape in, field over the top, gradient down the field.

Usage:
  python3 session_features.py --sessions sessions.json [--out matrix.json]
  python3 session_features.py --selftest        # runs the acceptance fixture, exits 0/1
Stdlib only.
"""
import argparse
import json
import math
import sys

SCHEMA = "vibrant/session-features@1"

FEATURE_NAMES = [
    "engine_solo",
    "engine_delegate",
    "engine_workflow",
    "routing_none",
    "routing_homogeneous",
    "routing_cross_family",
    "effort_low",
    "effort_medium",
    "effort_high",
    "effort_xhigh",
    "effort_max",
    "effort_unknown",
    "orch_fire",
    "worker_fire",
    "fanout",
    "turns",
    "touch_rate",
    "cache_read_pct",
]

TIER = {
    "haiku-4-5": 0.15, "haiku-4-5-20251001": 0.15, "fable-5": 0.25,
    "sonnet-4-6": 0.55, "sonnet-5": 0.6, "opus-4-6": 0.85, "opus-4-8": 0.9,
    "opus-5": 1.0,
}

FANOUT_CAP = 32
TURNS_CAP = 200

_ENGINES = {"solo": "engine_solo", "delegate": "engine_delegate",
            "workflow": "engine_workflow"}
_ROUTINGS = {"none": "routing_none", "homogeneous": "routing_homogeneous",
             "cross-family": "routing_cross_family"}
_EFFORTS = {"low": "effort_low", "medium": "effort_medium",
            "high": "effort_high", "xhigh": "effort_xhigh",
            "max": "effort_max"}


def base(m):
    return (m or "").split("[")[0].replace("claude-", "")


def features(m):
    """Pure, deterministic feature vector for one session metric dict.
    Never mutates m. Length len(FEATURE_NAMES), every element in [0, 1]."""
    v = [0.0] * len(FEATURE_NAMES)

    engine_slot = _ENGINES.get(m.get("engine"))
    if engine_slot:
        v[FEATURE_NAMES.index(engine_slot)] = 1.0

    routing_slot = _ROUTINGS.get(m.get("routing"))
    if routing_slot:
        v[FEATURE_NAMES.index(routing_slot)] = 1.0

    effort_slot = _EFFORTS.get(m.get("effort"))
    if effort_slot:
        v[FEATURE_NAMES.index(effort_slot)] = 1.0
    else:
        v[FEATURE_NAMES.index("effort_unknown")] = 1.0

    model = m.get("model")
    if model:
        v[FEATURE_NAMES.index("orch_fire")] = TIER.get(base(model), 0.5)
    else:
        v[FEATURE_NAMES.index("orch_fire")] = 0.5

    worker = m.get("worker")
    if worker is None or worker == "solo":
        worker_fire = 0.0
    else:
        worker_fire = TIER.get(base(worker), 0.5)
    v[FEATURE_NAMES.index("worker_fire")] = worker_fire

    fanout = m.get("fanout") or 0
    v[FEATURE_NAMES.index("fanout")] = min(
        math.log1p(fanout) / math.log1p(FANOUT_CAP), 1.0)

    n_turns = m.get("n_turns") or 0
    v[FEATURE_NAMES.index("turns")] = min(
        math.log1p(n_turns) / math.log1p(TURNS_CAP), 1.0)

    touches = m.get("touches") or 0
    v[FEATURE_NAMES.index("touch_rate")] = min(
        touches / max(n_turns, 1), 1.0)

    cache_r = m.get("cache_r") or 0
    in_tok = m.get("in_tok") or 0
    cache_w = m.get("cache_w") or 0
    denom = cache_r + in_tok + cache_w
    v[FEATURE_NAMES.index("cache_read_pct")] = (cache_r / denom) if denom else 0.0

    return v


def feature_matrix(sessions):
    """Pure function of the session list. Rows in input order."""
    rows = []
    for m in sessions:
        rows.append({
            "sid": m.get("sid"),
            "day": m.get("day"),
            "vec": features(m),
        })
    return {"schema": SCHEMA, "names": FEATURE_NAMES, "rows": rows}


def selftest():
    import test_session_features as t
    return t.main()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", help="JSON array of per-session metric dicts")
    ap.add_argument("--out", default=None, help="write matrix JSON here (else stdout)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.sessions:
        ap.error("--sessions is required (or use --selftest)")
    with open(args.sessions) as f:
        sessions = json.load(f)
    out = feature_matrix(sessions)
    text = json.dumps(out, indent=2, sort_keys=True) + "\n"
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"features written: {args.out} ({len(out['rows'])} rows)")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
