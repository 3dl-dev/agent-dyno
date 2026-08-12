#!/usr/bin/env python3
"""
harness-efficiency.py, P1 of the Harness Efficiency Protocol
(docs/specs/harness-efficiency-protocol.md).

Joins per-session SURVIVING work (born - same-session-killed chars) with FUEL
($ and tokens) and the engine classification, then reports the efficiency
VECTOR per engine and the Pareto frontier across engines. Deliberately NO
composite score: this session's own lesson is that a composite built mostly of
volume terms re-flatters the worst engine. The frontier is Pareto, not a rank.

Input: the snapshot JSONL (session/turn/code records) written by snapshot.py,
i.e. the mb-<host>.jsonl and mc-<host>.jsonl under a dated snapshot dir. Also
walks the raw transcripts under ~/.claude/projects once for per-session survival,
caching the result in survival-cache.json next to the snapshot so a re-run (and
harness-modeleffect, pointed at the same snapshot) reuses it.

Usage:
  python3 harness-efficiency.py <snapshot-dir>/mb-*.jsonl <snapshot-dir>/mc-*.jsonl

Stdlib only. Imports survival scan + cost from sibling modules.
"""
import json
import os
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import importlib
surv = importlib.import_module("model-behavior-survival")
from mb_cost import session_cost


def base(m):
    return (m or "").split("[")[0].replace("claude-", "")


def engine_class(s):
    if (s.get("workflows") or 0) > 0 or (s.get("wf_agents") or 0) > 0:
        return "workflow"
    if (s.get("plain_agents") or 0) > 0:
        return "delegate"
    return "solo"


def routing(orch_model, submix):
    if not submix:
        return "none"
    wb = {base(m) for m in submix}
    ob = base(orch_model)
    return "homogeneous" if wb == {ob} else "cross:" + "+".join(sorted(b for b in wb if b != ob))


def load_snapshot(paths):
    sessions, code, touches = {}, {}, defaultdict(int)
    for p in paths:
        for line in open(p):
            try:
                r = json.loads(line)
            except Exception:
                continue
            k = r.get("k")
            if k == "session":
                sessions[r["sess"]] = r
            elif k == "code":
                code[r["sess"]] = r
            elif k == "turn":
                touches[r["sess"]] += (r.get("nudge") or 0) + (r.get("ends_q") or 0) + (r.get("interrupted") or 0)
    return sessions, code, touches


AXES = [
    # (key, label, better)  better: "lo" = lower is better, "hi" = higher
    ("dollars_per_survkb", "$/surv-KB", "lo"),
    ("survkb_per_outmtok", "survKB/Mtok-out", "hi"),
    ("touch_per_survkb", "touches/surv-KB", "lo"),
    ("waste", "waste %", "lo"),
    ("cache_share", "cache-read %", "hi"),
    ("orchtok_per_survkb", "orch-tok/surv-KB", "lo"),
]


def vector(acc):
    surv_kb = max(1e-9, (acc["born"] - acc["killed"]) / 1000.0)
    out_mtok = max(1e-9, acc["out_tok"] / 1e6)
    allin = max(1e-9, acc["cache_r"] + acc["in"] + acc["cache_w"])
    return {
        "dollars_per_survkb": acc["dollars"] / surv_kb,
        "survkb_per_outmtok": surv_kb / out_mtok,
        "touch_per_survkb": acc["touches"] / surv_kb,
        "waste": 100 * acc["killed"] / max(1, acc["born"]),
        "cache_share": 100 * acc["cache_r"] / allin,
        "orchtok_per_survkb": acc["orch_out"] / surv_kb,
    }


def dominates(a, b):
    """a Pareto-dominates b: at least as good on every axis, better on one."""
    ge = True
    gt = False
    for key, _lbl, better in AXES:
        av, bv = a[key], b[key]
        if better == "lo":
            if av > bv + 1e-9:
                ge = False
            if av < bv - 1e-9:
                gt = True
        else:
            if av < bv - 1e-9:
                ge = False
            if av > bv + 1e-9:
                gt = True
    return ge and gt


def aggregate(groups, sessions, code, touches, survmap):
    acc = defaultdict(lambda: defaultdict(float))
    n = defaultdict(int)
    for sid, g in groups.items():
        if sid not in survmap:
            continue
        born, killed = survmap[sid]
        s = sessions[sid]
        c = code.get(sid) or {}
        orch = c.get("orch") or {}
        work = c.get("work") or {}
        a = acc[g]
        n[g] += 1
        a["born"] += born
        a["killed"] += killed
        a["dollars"] += session_cost(s)
        a["out_tok"] += orch.get("out_tok", 0) + work.get("out_tok", 0)
        a["orch_out"] += orch.get("out_tok", 0)
        a["cache_r"] += orch.get("cache_r_tok", 0) + work.get("cache_r_tok", 0)
        a["cache_w"] += orch.get("cache_w_tok", 0) + work.get("cache_w_tok", 0)
        a["in"] += orch.get("in_tok", 0) + work.get("in_tok", 0)
        a["touches"] += touches.get(sid, 0)
    return acc, n


def report(title, acc, n):
    vecs = {g: vector(a) for g, a in acc.items() if (a["born"] - a["killed"]) > 0}
    frontier = {g for g in vecs if not any(dominates(vecs[h], vecs[g]) for h in vecs if h != g)}
    print("\n" + "=" * 92)
    print(title)
    hdr = f"{'engine':16}{'sess':>5}  " + "".join(f"{lbl:>16}" for _k, lbl, _b in AXES) + "  frontier"
    print(hdr)
    print("-" * len(hdr))
    # order by dollars_per_survkb ascending (cheapest surviving work first)
    for g in sorted(vecs, key=lambda x: vecs[x]["dollars_per_survkb"]):
        v = vecs[g]
        cells = ""
        for key, _lbl, better in AXES:
            best = (min if better == "lo" else max)(vv[key] for vv in vecs.values())
            mark = "*" if abs(v[key] - best) < 1e-9 else " "
            cells += f"{v[key]:>15.2f}{mark}"
        print(f"{g:16}{n[g]:>5}  {cells}  {'PARETO' if g in frontier else ''}")
    print("  * = best on that axis.  PARETO = not dominated on all axes by another engine.")


def main(paths):
    sessions, code, touches = load_snapshot(paths)
    print("scanning raw transcripts for per-session survival ...", file=sys.stderr)
    snap_dir = os.path.dirname(os.path.abspath(paths[0]))
    cache_path = os.path.join(snap_dir, "survival-cache.json")
    survmap = surv.per_session_survival(cache_path=cache_path, verbose=True)
    print(f"  survival for {len(survmap)} sessions; {len(sessions)} in snapshot",
          file=sys.stderr)

    # by engine
    eng = {sid: engine_class(s) for sid, s in sessions.items()}
    acc, n = aggregate(eng, sessions, code, touches, survmap)
    report("EFFICIENCY VECTOR BY ENGINE  (fuel = $, tokens; work = surviving chars)",
           acc, n)

    # by engine x routing, delegating engines only (the opus-drives-X question)
    rte = {}
    for sid, s in sessions.items():
        if engine_class(s) in ("delegate", "workflow"):
            r = routing(s.get("model"), s.get("submix"))
            rte[sid] = f"{base(s.get('model'))} {engine_class(s)[:4]} {r}"
    acc2, n2 = aggregate(rte, sessions, code, touches, survmap)
    # only show routings with >=4 sessions to avoid noise
    keep = {g: a for g, a in acc2.items() if n2[g] >= 4}
    report("ROUTING x ENGINE  (>=4 sessions; who drives whom, with survival)",
           keep, n2)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        sys.exit(1)
    main(args)
