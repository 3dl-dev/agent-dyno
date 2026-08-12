#!/usr/bin/env python3
"""
harness-characterize.py, P0 of the Harness Efficiency Protocol
(docs/specs/harness-efficiency-protocol.md).

Classifies each session by the ENGINE it ran (solo / delegate / workflow),
not just the model, computes a first-cut harness fingerprint, and quantifies
how badly engine and model are entangled in the data. This is the prerequisite
question: any per-model efficiency number is a blend until we know how many
distinct engines produced it.

Input: the merged snapshot JSONL emitted by mb_snapshot.py, i.e. one or more
  mb-<host>.filtered.jsonl   (session + turn records from model-behavior.py)
  mc-<host>.filtered.jsonl   (code records from model-behavior-code.py)

Usage:
  python3 harness-characterize.py mb-*.jsonl mc-*.jsonl
  python3 harness-characterize.py model-behavior/snapshots/2026-08-11-workshop/*.filtered.jsonl

Stdlib only. Joins full cost via the sibling mb_cost module if importable.
"""
import json
import os
import sys
import statistics as st
from collections import defaultdict, Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
try:
    from mb_cost import session_cost
except Exception:
    session_cost = None


def base(m):
    return (m or "").split("[")[0].replace("claude-", "")


def engine_class(s):
    """solo | delegate | workflow, from the session's dispatch topology."""
    wf = s.get("workflows") or 0
    wa = s.get("wf_agents") or 0
    pa = s.get("plain_agents") or 0
    if wf > 0 or wa > 0:
        return "workflow"
    if pa > 0:
        return "delegate"
    return "solo"


def worker_mix(s):
    """token/agent-weighted base-model mix of the workers (submix)."""
    mix = s.get("submix") or {}
    out = Counter()
    for m, n in mix.items():
        out[base(m)] += n
    return out


def routing(orch_model, wmix):
    """homogeneous if workers share the orchestrator's base model, else cross."""
    if not wmix:
        return "none"
    worker_bases = set(wmix)
    ob = base(orch_model)
    if worker_bases == {ob}:
        return "homogeneous"
    return "cross:" + "+".join(sorted(b for b in worker_bases if b != ob)) or "cross"


def main(paths):
    sessions, code, turns = {}, {}, defaultdict(int)
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
                turns[r["sess"]] += 1

    # ── per-session characterization ──
    rows = []
    for sid, s in sessions.items():
        om = base(s.get("model"))
        eng = engine_class(s)
        wmix = worker_mix(s)
        c = code.get(sid) or {}
        orch = c.get("orch") or {}
        work = c.get("work") or {}

        def share(key):
            o, w = orch.get(key, 0), work.get(key, 0)
            return (w / (o + w)) if (o + w) else 0.0

        oe = orch.get("edits", 0)
        oc = orch.get("calls", 0)
        # parasitic load: orchestrator output tokens spent per surviving-ish edit
        total_edits = oe + work.get("edits", 0)
        parasite = (orch.get("out_tok", 0) / total_edits) if total_edits else 0.0
        # coordination fraction of orchestrator calls (non-edit calls)
        coord_frac = (1 - oe / oc) if oc else 0.0
        allcache = (orch.get("cache_r_tok", 0) + work.get("cache_r_tok", 0))
        allin = allcache + orch.get("in_tok", 0) + work.get("in_tok", 0) \
            + orch.get("cache_w_tok", 0) + work.get("cache_w_tok", 0)
        cache_share = (allcache / allin) if allin else 0.0
        dollars = session_cost(s) if session_cost else 0.0

        rows.append({
            "sid": sid, "orch": om, "engine": eng,
            "route": routing(s.get("model"), wmix),
            "wmix": dict(wmix),
            "fanout": (s.get("wf_agents", 0) / s["workflows"]) if s.get("workflows") else 0,
            "subs": (s.get("wf_agents", 0) + s.get("plain_agents", 0)),
            "deleg_edit": share("edits"),
            "deleg_tok": share("out_tok"),
            "parasite": parasite,
            "coord_frac": coord_frac,
            "cache_share": cache_share,
            "edits": total_edits,
            "dollars": dollars,
            "turns": turns.get(sid, 0),
        })

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return st.mean(xs) if xs else 0.0

    # ── 1. engine distribution ──
    print("=" * 74)
    print("ENGINE DISTRIBUTION")
    print(f"{'engine':10}{'sess':>6}{'turns':>7}{'edits':>8}{'$':>9}"
          f"{'deleg%':>8}{'fanout':>8}{'cacheRd%':>9}{'$/edit':>8}")
    by_eng = defaultdict(list)
    for r in rows:
        by_eng[r["engine"]].append(r)
    for eng in ("solo", "delegate", "workflow"):
        g = by_eng.get(eng, [])
        if not g:
            continue
        te, td = sum(r["edits"] for r in g), sum(r["dollars"] for r in g)
        print(f"{eng:10}{len(g):>6}{sum(r['turns'] for r in g):>7}{te:>8}"
              f"{td:>9.0f}{100*mean([r['deleg_tok'] for r in g]):>7.0f}%"
              f"{mean([r['fanout'] for r in g if r['fanout']]):>8.1f}"
              f"{100*mean([r['cache_share'] for r in g]):>8.0f}%"
              f"{td/max(1,te):>8.2f}")

    # ── 2. entanglement: engine × orchestrator model (session counts) ──
    print("\n" + "=" * 74)
    print("ENTANGLEMENT  (sessions by engine × orchestrator model)")
    models = sorted({r["orch"] for r in rows})
    print(f"{'engine':10}" + "".join(f"{m:>12}" for m in models) + f"{'row%':>7}")
    ncell = defaultdict(int)
    for r in rows:
        ncell[(r["engine"], r["orch"])] += 1
    N = len(rows)
    for eng in ("solo", "delegate", "workflow"):
        if eng not in by_eng:
            continue
        cells = [ncell[(eng, m)] for m in models]
        print(f"{eng:10}" + "".join(f"{c:>12}" for c in cells)
              + f"{100*sum(cells)/N:>6.0f}%")
    print(f"{'col%':10}" + "".join(
        f"{100*sum(ncell[(e,m)] for e in by_eng)/N:>11.0f}%" for m in models))
    print("\nReading: if a model appears under only one engine, its column is that "
          "engine.\nAny cross-model efficiency claim must condition on the engine.")

    # ── 3. model routing within delegating engines ──
    print("\n" + "=" * 74)
    print("ROUTING  (delegate + workflow sessions: who drives whom)")
    route = defaultdict(list)
    for r in rows:
        if r["engine"] in ("delegate", "workflow"):
            route[(r["orch"], r["route"])].append(r)
    print(f"{'orchestrator':>14}  {'routing':<22}{'sess':>5}{'subs':>6}"
          f"{'deleg%':>8}{'parasite':>9}{'$/edit':>8}")
    for (om, rt), g in sorted(route.items(), key=lambda kv: -len(kv[1])):
        te, td = sum(r["edits"] for r in g), sum(r["dollars"] for r in g)
        print(f"{om:>14}  {rt:<22}{len(g):>5}{mean([r['subs'] for r in g]):>6.1f}"
              f"{100*mean([r['deleg_tok'] for r in g]):>7.0f}%"
              f"{mean([r['parasite'] for r in g]):>9.0f}{td/max(1,te):>8.2f}")
    print("\nparasite = orchestrator output tokens burned per edit landed "
          "(coordination fuel).")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        sys.exit(1)
    main(args)
