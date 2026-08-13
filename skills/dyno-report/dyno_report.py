#!/usr/bin/env python3
# REFERENCE BUILD. Source of truth: dyno_report.spec.md (what it must do)
# + test_dyno_report.py (the verification). Code is a regenerable artifact:
# rebuild it from the spec and the acceptance test must still pass. See SOURCE.md.
"""
dyno_report.py, the turn-key driver behind the dyno-report skill.

Reason to exist: the efficiency report must be accurate and IDENTICAL whatever
model or harness runs the skill. An LLM assembling the pipeline by hand cannot
promise that; this deterministic driver can. The model does zero computation: it
reads governance, invokes this driver, and narrates the bundle emitted here.

Given a fuel snapshot (built by the harness adapter), a set of repos, and a
frontier commons, it computes the protocol efficiency vector per engine and per
(engine, model), the git-survival numerator per repo, the same-shape comparison
against the frontier (engine x effort x model-tier), the claim verdicts it has
data for, and the named confounds. Output is report.json (the contract) and
report.md (rendered by a fixed template, no model in the loop).

Usage:
  dyno_report --harness claude-code --repos <path>[,<path>...] \
      --snapshot <dir> [--since <git-approxidate>] [--frontier <path>] \
      [--now <epoch>] --out <dir>

Stdlib only. Deterministic: same (snapshot, git HEADs, frontier, since) inputs
give byte-identical report.json regardless of the model that invoked it.
"""
import argparse
import glob
import hashlib
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "core"))

import survival_git  # noqa: E402  (core/survival_git.py, after path insert)

# ── model -> tier, so operator cells (concrete models) match frontier role tiers
STRONG = {"opus-5", "opus-4-8", "sonnet-5", "opus-4-6", "sonnet-4-6"}
CHEAP = {"fable-5", "haiku-4-5", "haiku-4-5-20251001"}


def base_model(m):
    """Collapse a model id to its base family key used across the toolkit."""
    m = m or ""
    for pref in ("opus-5", "opus-4-8", "opus-4-6", "sonnet-5", "sonnet-4-6",
                 "haiku-4-5", "fable-5"):
        if pref in m:
            return pref
    return m or "none"


def model_tier(m):
    b = base_model(m)
    if b in CHEAP:
        return "cheap"
    if b in STRONG:
        return "strong"
    return "unknown"


def modal(values, default="unknown"):
    """Most common value; ties broken by sorted value so output is deterministic
    regardless of hash-seed / set-iteration order across processes."""
    if not values:
        return default
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return sorted(counts, key=lambda v: (-counts[v], v))[0]


def engine_of(sess):
    if (sess.get("workflows") or 0) > 0 or (sess.get("wf_agents") or 0) > 0:
        return "workflow"
    if (sess.get("plain_agents") or 0) > 0:
        return "delegate"
    return "solo"


def load_adapter_cost(harness):
    """Return (session_cost, usage_field) for the harness adapter, or (None,None).

    usage_field(usage_dict, kind) resolves a token count across the toolkit's
    key aliases (in/out/cache_w/cache_r), so token aggregation matches the same
    main_usage/sub_usage buckets the dollar figure is priced from.
    """
    adir = os.path.join(ROOT, "adapters", harness)
    if not os.path.isdir(adir):
        return None, None
    sys.path.insert(0, adir)
    try:
        import mb_cost  # noqa: E402
        return mb_cost.session_cost, mb_cost._usage_field
    except Exception:
        return None, None


def usage_sum(sess, kind, usage_field):
    """Sum a token kind across main_usage + sub_usage (orchestrator + subagents)."""
    total = 0
    for key in ("main_usage", "sub_usage"):
        for _model, usage in (sess.get(key) or {}).items():
            total += usage_field(usage, kind)
    return total


def load_snapshot(snapshot_dir):
    """Load sessions, turns-by-session, code-by-session, survival-by-session."""
    sessions, turns, code = {}, defaultdict(list), {}
    for p in glob.glob(os.path.join(snapshot_dir, "mb-*.jsonl")):
        for line in open(p):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("k") == "session":
                sessions[r["sess"]] = r
            elif r.get("k") == "turn":
                turns[r["sess"]].append(r)
    for p in glob.glob(os.path.join(snapshot_dir, "mc-*.jsonl")):
        for line in open(p):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("k") == "code":
                code[r["sess"]] = r
    surv_path = os.path.join(snapshot_dir, "survival-cache.json")
    survival = json.load(open(surv_path)) if os.path.exists(surv_path) else {}
    return sessions, turns, code, survival


def session_metrics(sess, turns, code, survival, session_cost, usage_field):
    """Per-session primitives the vector is built from. None if no survival.

    Token aggregates come from main_usage + sub_usage (so subagent output is
    counted, matching the dollar basis); effort and human-touches come from the
    main-session turn records, which carry them.
    """
    sid = sess["sess"]
    sv = survival.get(sid)
    if not sv or not sv.get("born"):
        return None
    T = turns.get(sid, [])
    if usage_field:
        out_tok = usage_sum(sess, "out", usage_field)
        in_tok = usage_sum(sess, "in", usage_field)
        cache_r = usage_sum(sess, "cache_r", usage_field)
        cache_w = usage_sum(sess, "cache_w", usage_field)
    else:  # no adapter: fall back to main-session turn sums
        out_tok = sum(t.get("out_tok", 0) for t in T)
        in_tok = sum(t.get("in_tok", 0) for t in T)
        cache_r = sum(t.get("cache_r_tok", 0) for t in T)
        cache_w = sum(t.get("cache_w_tok", 0) for t in T)
    touches = sum(1 for t in T if t.get("user_chars", 0) > 0)
    effort = modal([t.get("effort") for t in T if t.get("effort")])
    c = code.get(sid) or {}
    orch_out = usage_field(c.get("orch") or {}, "out") if usage_field \
        else (c.get("orch") or {}).get("out_tok", 0)
    dollars = session_cost(sess) if session_cost else 0.0
    return {
        "sid": sid,
        "engine": engine_of(sess),
        "model": base_model(sess.get("model")),
        "effort": effort,
        "born": sv["born"],
        "killed": sv.get("killed", 0),
        "out_tok": out_tok,
        "in_tok": in_tok,
        "cache_r": cache_r,
        "cache_w": cache_w,
        "orch_out": orch_out,
        "touches": touches,
        "dollars": dollars,
    }


def vector(cells):
    """Aggregate a list of per-session metric dicts into one protocol vector."""
    born = sum(m["born"] for m in cells)
    killed = sum(m["killed"] for m in cells)
    survc = born - killed
    survkb = survc / 1024 if survc > 0 else 0.0
    out_tok = sum(m["out_tok"] for m in cells)
    dollars = sum(m["dollars"] for m in cells)
    cache_r = sum(m["cache_r"] for m in cells)
    in_tok = sum(m["in_tok"] for m in cells)
    cache_w = sum(m["cache_w"] for m in cells)
    orch_out = sum(m["orch_out"] for m in cells)
    touches = sum(m["touches"] for m in cells)
    read_den = cache_r + in_tok + cache_w
    return {
        "sessions": len(cells),
        "dollars": round(dollars, 2),
        "surv_kb": round(survkb, 2),
        "d_per_survkb": round(dollars / survkb, 4) if survkb else None,
        "survkb_per_outmtok": round(survkb / (out_tok / 1e6), 2) if out_tok else None,
        "waste_pct": round(100 * killed / born, 2) if born else None,
        "cache_read_pct": round(100 * cache_r / read_den, 2) if read_den else None,
        "orch_tok_per_survkb": round(orch_out / survkb, 2) if survkb else None,
        "touches_per_survkb": round(touches / survkb, 4) if survkb else None,
    }


# axes and whether higher is better, for Pareto
AXES = [
    ("d_per_survkb", False),
    ("survkb_per_outmtok", True),
    ("waste_pct", False),
    ("cache_read_pct", True),
    ("orch_tok_per_survkb", False),
    ("touches_per_survkb", False),
]


def _dominates(a, b):
    """a dominates b: at least as good on every axis, strictly better on one."""
    better_or_equal_all = True
    strictly_better_one = False
    for key, higher in AXES:
        av, bv = a.get(key), b.get(key)
        if av is None or bv is None:
            continue
        ge = (av >= bv) if higher else (av <= bv)
        gt = (av > bv) if higher else (av < bv)
        if not ge:
            better_or_equal_all = False
        if gt:
            strictly_better_one = True
    return better_or_equal_all and strictly_better_one


def pareto_flags(named_vectors):
    """named_vectors: {name: vector}. Return {name: bool}."""
    flags = {}
    for name, v in named_vectors.items():
        dominated = any(_dominates(o, v) for on, o in named_vectors.items() if on != name)
        flags[name] = not dominated
    return flags


def same_shape(op_cells_by_ee, frontier):
    """For each operator (engine, effort) cell, match frontier entries of the
    same shape (same engine, same effort). Report operator vs frontier, or state
    no-same-shape-entry. Never compares across shapes."""
    out = []
    fentries = frontier.get("entries", [])
    for (engine, effort), cells in sorted(op_cells_by_ee.items()):
        opv = vector(cells)
        # dominant orchestrator tier in this operator cell
        op_tier = modal([model_tier(m["model"]) for m in cells])
        matches = []
        for e in fentries:
            if e.get("engine") == engine and e.get("effort") == effort:
                matches.append({
                    "id": e.get("id"),
                    "orchestrator_tier": (e.get("model_roles") or {}).get("orchestrator"),
                    "vector": e.get("vector"),
                    "technique": e.get("technique"),
                    "proof": e.get("proof"),
                })
        rec = {
            "engine": engine,
            "effort": effort,
            "operator_orchestrator_tier": op_tier,
            "operator_vector": opv,
        }
        if matches:
            rec["status"] = "matched"
            rec["frontier_matches"] = matches
            # nearest advice: the match that most beats the operator's worst axis
            worst_axis = _worst_axis(opv)
            rec["worst_axis"] = worst_axis
            rec["advice_from"] = _advice(worst_axis, opv, matches)
        else:
            rec["status"] = "no-same-shape-entry"
            rec["frontier_matches"] = []
        out.append(rec)
    return out


def _worst_axis(opv):
    """Which axis is the operator worst on, relative to a naive target."""
    # heuristic: waste_pct if it is high, else d_per_survkb
    if opv.get("waste_pct") is not None and opv["waste_pct"] >= 25:
        return "waste_pct"
    return "d_per_survkb"


def _advice(axis, opv, matches):
    higher = dict(AXES).get(axis, False)
    best = None
    for m in matches:
        fv = (m.get("vector") or {})
        # frontier vectors use dollars_per_survkb / waste_pct keys
        key = {"d_per_survkb": "dollars_per_survkb", "waste_pct": "waste_pct"}.get(axis, axis)
        val = fv.get(key)
        if val is None:
            continue
        if best is None or (val > best[1] if higher else val < best[1]):
            best = (m.get("id"), val, m.get("technique"))
    if not best:
        return None
    return {"frontier_id": best[0], "their_value": best[1], "technique": best[2]}


def topline(metrics):
    """The one meter: surviving-KB per dollar. Unbounded, higher is better."""
    survc = sum(m["born"] - m["killed"] for m in metrics)
    dollars = sum(m["dollars"] for m in metrics)
    survkb = survc / 1024 if survc > 0 else 0.0
    eq = round(survkb / dollars, 4) if dollars else None
    return {"eq": eq, "unit": "surviving KB per dollar",
            "surv_kb": round(survkb, 2), "dollars": round(dollars, 2),
            "sessions": len(metrics), "_survkb": survkb, "_dollars": dollars}


def frontier_eq(entry):
    d = (entry.get("vector") or {}).get("dollars_per_survkb")
    return (1.0 / d) if d else None


def best_lever(by_ee_cells, frontier, total_survkb, total_dollars):
    """The single tweak with the largest predicted topline gain: the operator's
    worst same-shape cell vs the same-shape frontier entry that beats it. None if
    nothing on the frontier beats the operator at their own shape."""
    if not total_dollars:
        return None
    base_eq = total_survkb / total_dollars
    # best frontier entry per (engine, effort)
    fmap = {}
    for e in frontier.get("entries", []):
        key = (e.get("engine"), e.get("effort"))
        feq = frontier_eq(e)
        if feq is None:
            continue
        if key not in fmap or feq > frontier_eq(fmap[key]):
            fmap[key] = e
    best = None
    for (engine, effort), cells in by_ee_cells.items():
        fe = fmap.get((engine, effort))
        if not fe:
            continue
        cell_survc = sum(m["born"] - m["killed"] for m in cells)
        cell_survkb = cell_survc / 1024 if cell_survc > 0 else 0.0
        cell_dollars = sum(m["dollars"] for m in cells)
        if cell_survkb <= 0 or cell_dollars <= 0:
            continue
        cell_eq = cell_survkb / cell_dollars
        feq = frontier_eq(fe)
        if feq <= cell_eq:  # frontier does not beat you here: no lever
            continue
        # counterfactual: same surviving work, at the frontier's efficiency
        cf_dollars = cell_survkb / feq
        new_dollars = total_dollars - cell_dollars + cf_dollars
        new_eq = total_survkb / new_dollars if new_dollars > 0 else None
        if new_eq is None:
            continue
        cand = {"engine": engine, "effort": effort,
                "frontier_id": fe.get("id"),
                "tweak": fe.get("lever") or fe.get("technique"),
                "proof": fe.get("proof"),
                "your_cell_eq": round(cell_eq, 4),
                "frontier_cell_eq": round(feq, 4),
                "predicted_topline_eq": round(new_eq, 4),
                "predicted_delta": round(new_eq - base_eq, 4)}
        if best is None or cand["predicted_delta"] > best["predicted_delta"]:
            best = cand
    return best


def claim_verdicts(by_engine, metrics):
    """Mechanical verdicts for the claims we have data for this run."""
    out = []
    # C1: cost is O(reads) -- read machinery share of $
    read_tok = sum(m["cache_r"] + m["in_tok"] + m["cache_w"] for m in metrics)
    # rough: reads vs generation by token share (generation = out_tok)
    out_tok = sum(m["out_tok"] for m in metrics)
    if read_tok + out_tok:
        read_share = 100 * read_tok / (read_tok + out_tok)
        out.append({"id": "C1", "claim": "cost is O(reads)",
                    "metric": f"read tokens = {read_share:.1f}% of (read+gen) tokens",
                    "verdict": "supported" if read_share > 70 else "not-supported"})
    # C7/C8: solo cleanest & cheapest
    solo = by_engine.get("solo")
    if solo:
        cleanest = min((v for v in by_engine.values() if v["waste_pct"] is not None),
                       key=lambda v: v["waste_pct"], default=None)
        cheapest = min((v for v in by_engine.values() if v["d_per_survkb"] is not None),
                       key=lambda v: v["d_per_survkb"], default=None)
        out.append({"id": "C7/C8", "claim": "solo strong model cleanest & cheapest",
                    "metric": f"solo waste={solo['waste_pct']}% $/survKB={solo['d_per_survkb']}",
                    "verdict": "supported" if (cleanest is solo and cheapest is solo)
                    else "partial"})
    return out


def confounds(metrics, numerator, since):
    out = []
    out.append(f"Horizon: survival here is same-session (killed within the run), "
               f"and the git numerator is measured at HEAD over '{since}'. Not a "
               f"durable day/week horizon.")
    small = [f"{e}" for e, v in {}.items()]
    n = len(metrics)
    if n < 30:
        out.append(f"Small N: only {n} code-sessions with survival in the window; "
                   f"per-cell numbers move on a few sessions.")
    # bulk-import repos in the numerator
    for r in numerator["repos"]:
        if r.get("commits") and r["added"] and r["commits"] <= 2 and r["added"] > 20000:
            out.append(f"Terrain: repo '{r['name']}' added {r['added']:,} lines in "
                       f"{r['commits']} commit(s) at {r['pct']:.0f}% survival, likely a "
                       f"bulk import, not authored work; it inflates aggregate survival.")
    return out


def measure_vs_baseline(current_eq, baseline_path):
    """Close the loop: actual EQ move since a prior report, beside its prediction."""
    if not baseline_path or not os.path.exists(baseline_path):
        return None
    prev = json.load(open(baseline_path))
    prev_eq = (prev.get("topline") or {}).get("eq")
    predicted = (prev.get("lever") or {}).get("predicted_delta")
    if prev_eq is None or current_eq is None:
        return None
    return {"baseline_eq": prev_eq, "current_eq": current_eq,
            "actual_delta": round(current_eq - prev_eq, 4),
            "previously_predicted_delta": predicted}


def build_report(snapshot_dir, repos, since, frontier_path, harness, now,
                 baseline_path=None):
    session_cost, usage_field = load_adapter_cost(harness)
    sessions, turns, code, survival = load_snapshot(snapshot_dir)
    metrics = []
    for sid, s in sessions.items():
        m = session_metrics(s, turns, code, survival, session_cost, usage_field)
        if m:
            metrics.append(m)
    metrics.sort(key=lambda m: m["sid"])  # deterministic order

    # vectors by engine and by (engine, model)
    by_eng_cells = defaultdict(list)
    by_em_cells = defaultdict(list)
    by_ee_cells = defaultdict(list)
    for m in metrics:
        by_eng_cells[m["engine"]].append(m)
        by_em_cells[(m["engine"], m["model"])].append(m)
        by_ee_cells[(m["engine"], m["effort"])].append(m)
    by_engine = {e: vector(c) for e, c in by_eng_cells.items()}
    pflags = pareto_flags(by_engine)
    vector_by_engine = []
    for e in sorted(by_engine):
        row = {"engine": e, **by_engine[e], "pareto": pflags[e]}
        vector_by_engine.append(row)
    vector_by_engine_model = []
    for (e, mdl) in sorted(by_em_cells):
        vector_by_engine_model.append({"engine": e, "model": mdl,
                                       **vector(by_em_cells[(e, mdl)])})

    # numerator per repo
    repo_rows = []
    tot_add = tot_surv = 0
    for repo in repos:
        r = survival_git.survival(repo, since, now=now)
        name = os.path.basename(os.path.normpath(repo))
        if r is None:
            repo_rows.append({"name": name, "commits": 0, "added": 0,
                              "surviving": 0, "pct": None})
            continue
        repo_rows.append({"name": name, "commits": r["commits"], "added": r["added"],
                          "surviving": r["surviving"], "pct": round(r["pct"], 2)})
        tot_add += r["added"]
        tot_surv += r["surviving"]
    numerator = {"repos": repo_rows, "total_added": tot_add,
                 "total_surviving": tot_surv,
                 "pct": round(100 * tot_surv / tot_add, 2) if tot_add else None}

    frontier = json.load(open(frontier_path)) if os.path.exists(frontier_path) else {"entries": []}
    ss = same_shape(by_ee_cells, frontier)
    tl = topline(metrics)
    lever = best_lever(by_ee_cells, frontier, tl["_survkb"], tl["_dollars"])
    tl = {k: v for k, v in tl.items() if not k.startswith("_")}  # drop internals
    measure = measure_vs_baseline(tl["eq"], baseline_path)

    # provenance
    repo_prov = []
    for repo in repos:
        head = survival_git.git(repo, "rev-parse", "HEAD").strip()
        repo_prov.append({"name": os.path.basename(os.path.normpath(repo)),
                          "head": head})
    fbytes = open(frontier_path, "rb").read() if os.path.exists(frontier_path) else b""
    report = {
        "provenance": {
            "harness": harness,
            "since": since,
            "snapshot": os.path.basename(os.path.normpath(snapshot_dir)),
            "sessions_with_survival": len(metrics),
            "repos": repo_prov,
            "frontier_sha256": hashlib.sha256(fbytes).hexdigest() if fbytes else None,
            "driver": "dyno_report/1",
        },
        "governance": {
            "clean": True,
            "assert": "engine-craft only; no individual-vs-product, no person-vs-person",
            "constitution": "docs/governance.md",
        },
        "topline": tl,
        "lever": lever,
        "measure": measure,
        "vector_by_engine": vector_by_engine,
        "vector_by_engine_model": vector_by_engine_model,
        "numerator": numerator,
        "same_shape": ss,
        "claims": claim_verdicts(by_engine, metrics),
        "confounds": confounds(metrics, numerator, since),
    }
    return report


def render_md(report):
    """The functional surface: one number, one lever, a measurable delta. Short
    by design. All the machinery stays in report.json."""
    tl = report["topline"]
    lever = report.get("lever")
    measure = report.get("measure")
    L = []
    if tl["eq"] is None:
        return "# Your setup\n\nNot enough surviving-work data in this window yet.\n"
    L.append(f"# Your setup: {tl['eq']} surviving KB per dollar")
    L.append("")
    L.append(f"Higher is better. That is durable code per dollar of tokens, over "
             f"{tl['sessions']} sessions. Nothing here leaves your machine.")
    L.append("")
    if lever:
        L.append("## Your biggest lever")
        L.append("")
        L.append(f"{lever['tweak']}")
        L.append("")
        L.append(f"Setups shaped like yours ({lever['engine']}, {lever['effort']} "
                 f"effort) that do this run at about {lever['frontier_cell_eq']} "
                 f"per dollar, against your {lever['your_cell_eq']}.")
        L.append(f"**Predicted move: +{lever['predicted_delta']}** "
                 f"(to about {lever['predicted_topline_eq']}). Try it, then run "
                 f"this again with --baseline pointed at this report.json, and it "
                 f"will tell you if the number actually moved.")
    else:
        L.append("You are at the frontier for every shape we can compare. No lever "
                 "to suggest; contribute your result so the next person can learn "
                 "from it.")
    L.append("")
    if measure:
        L.append("## Since last time")
        L.append("")
        arrow = "up" if measure["actual_delta"] > 0 else \
                ("flat" if measure["actual_delta"] == 0 else "down")
        pred = measure["previously_predicted_delta"]
        pred_s = f"predicted +{pred}, " if pred is not None else ""
        L.append(f"{measure['baseline_eq']} to {measure['current_eq']} "
                 f"({pred_s}actual {measure['actual_delta']:+}, {arrow}).")
        L.append("")
    L.append("---")
    L.append("_Full vector, fingerprint, per-repo survival, claim verdicts, and "
             "confounds are in report.json. Open it only if you want the "
             "derivation._")
    L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--harness", default="claude-code")
    ap.add_argument("--repos", default="")
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--since", default="30.days.ago")
    ap.add_argument("--frontier", default=os.path.join(ROOT, "frontier",
                                                       "reference-frontier.json"))
    ap.add_argument("--now", type=float, default=None,
                    help="fixed epoch for deterministic age buckets; default clock")
    ap.add_argument("--baseline", default=None,
                    help="a prior report.json; show the actual EQ move since it")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    repos = [os.path.expanduser(r) for r in args.repos.split(",") if r]
    report = build_report(args.snapshot, repos, args.since, args.frontier,
                          args.harness, args.now,
                          baseline_path=os.path.expanduser(args.baseline)
                          if args.baseline else None)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "report.json"), "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")
    with open(os.path.join(args.out, "report.md"), "w") as f:
        f.write(render_md(report))
    print(os.path.join(args.out, "report.json"))


if __name__ == "__main__":
    main()
