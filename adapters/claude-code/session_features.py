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
import re
import sys
from collections import defaultdict

# v2: the rig as an orchestration mix. v3: whether the workers coordinate. No capability
# tier lives here; the fingerprint is observable STRUCTURE only (depth, fanout, model-family
# spread, worker file-sharing), and how good a rig is gets measured by the field, never
# asserted by a prior. See session_features.spec.md ("No capability priors") and
# docs/governance.md.
SCHEMA = "vibrant/session-features@3"

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
    "fanout",
    "turns",
    "touch_rate",
    "cache_read_pct",
    "depth",
    "family_diversity",
    "coordination",
]

FANOUT_CAP = 32
TURNS_CAP = 200
DEPTH_CAP = 4     # solo 0, one layer .25, sub-orchestrator .5, three deep .75, 4+ 1.0
FAMILY_CAP = 6    # normalizes family entropy absolutely, not by this tree's family count
COORD_CAP = 0.20  # siloing is the norm, so expand the low range of shared-file fraction

_ENGINES = {"solo": "engine_solo", "delegate": "engine_delegate",
            "workflow": "engine_workflow"}
_ROUTINGS = {"none": "routing_none", "homogeneous": "routing_homogeneous",
             "cross-family": "routing_cross_family"}
_EFFORTS = {"low": "effort_low", "medium": "effort_medium",
            "high": "effort_high", "xhigh": "effort_xhigh",
            "max": "effort_max"}


def base(m):
    return (m or "").split("[")[0].replace("claude-", "")


def family(model):
    """The model's FAMILY: the leading alphabetic run of its base name (opus, sonnet,
    haiku, qwen, llama, gpt, ...). An objective, vendor-given grouping with NO ordering:
    grouping by family name is observation; ranking families by firepower was the bias
    v2 removed. opus-5 and opus-4-8 are both `opus`."""
    b = base(model).lower()
    mt = re.match(r"[a-z]+", b)
    return mt.group(0) if mt else (b or "unknown")


def _depth(m):
    """Orchestration nesting depth, normalized. Falls back to the engine class when the
    extractor did not record a tree depth (solo -> 0, delegate/workflow -> 1)."""
    d = m.get("depth")
    if d is None:
        d = 0 if m.get("engine") in (None, "solo") else 1
    return min(max(d, 0) / DEPTH_CAP, 1.0)


def _tree_family_weights(m):
    """Output-token-weighted census over model FAMILIES across the whole tree, the
    orchestrator included. Reads `tree_mix` when present (`model -> weight` or
    `model -> {weight, local}`); otherwise synthesizes from the orchestrator `model` plus
    the one-level `submix`/`worker`, so v1 dicts still embed."""
    w = defaultdict(float)
    tm = m.get("tree_mix")
    if tm:
        for model, val in tm.items():
            weight = val.get("weight", 0.0) if isinstance(val, dict) else val
            if weight and weight > 0:
                w[family(model)] += weight
        return w
    if m.get("model"):
        w[family(m["model"])] += 1.0
    sub = m.get("submix") or {}
    if sub:
        for wm, n in sub.items():
            if n and n > 0:
                w[family(wm)] += n
    elif m.get("worker") and m.get("worker") != "solo":
        w[family(m["worker"])] += 1.0
    return w


def _family_diversity(m):
    """Normalized Shannon entropy of the tree's model-family mix. One family (all opus,
    any versions) -> 0.0; an even spread across FAMILY_CAP+ families -> ~1.0."""
    w = _tree_family_weights(m)
    total = sum(w.values())
    if total <= 0 or len(w) <= 1:
        return 0.0
    h = 0.0
    for weight in w.values():
        p = weight / total
        if p > 0:
            h -= p * math.log(p)
    return min(h / math.log(FAMILY_CAP), 1.0)


def _coordination(m):
    """How much sibling workers SHARE work vs SILO: the fraction of the tree's edited files
    that two or more workers touched, expanded by COORD_CAP because siloing is the norm.
    Fully siloed (disjoint files) -> 0.0; heavily shared -> ~1.0. 0.0 with fewer than two
    workers (a lone actor cannot coordinate). NEUTRAL: high overlap can be coordination or
    conflict; the field decides which, never this axis."""
    wf = m.get("worker_files")
    if not wf or len(wf) < 2:
        return 0.0
    seen = {}
    for files in wf:
        for f in set(files or []):
            seen[f] = seen.get(f, 0) + 1
    distinct = len(seen)
    if distinct == 0:
        return 0.0
    shared = sum(1 for n in seen.values() if n >= 2)
    return min(1.0, (shared / distinct) / COORD_CAP)


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

    v[FEATURE_NAMES.index("depth")] = _depth(m)
    v[FEATURE_NAMES.index("family_diversity")] = _family_diversity(m)
    v[FEATURE_NAMES.index("coordination")] = _coordination(m)

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
