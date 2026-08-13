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
import datetime
import glob
import hashlib
import html as _html
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
    # babysitting signals: times you had to push it, and times it handed back
    # asking. nudge = you told it to continue; interrupted = you had to stop it;
    # ends_q = it ended a turn on a question rather than doing the obvious thing.
    nudges = sum(1 for t in T if t.get("nudge"))
    interrupts = sum(1 for t in T if t.get("interrupted"))
    ends_q = sum(1 for t in T if t.get("ends_q"))
    n_turns = len(T)
    effort = modal([t.get("effort") for t in T if t.get("effort")])
    c = code.get(sid) or {}
    orch_out = usage_field(c.get("orch") or {}, "out") if usage_field \
        else (c.get("orch") or {}).get("out_tok", 0)
    dollars = session_cost(sess) if session_cost else 0.0
    return {
        "sid": sid,
        "day": sess.get("day"),
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
        "nudges": nudges,
        "interrupts": interrupts,
        "ends_q": ends_q,
        "n_turns": n_turns,
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


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _iso_week(day):
    y, m, d = (int(x) for x in day.split("-")[:3])
    iso = datetime.date(y, m, d).isocalendar()
    return iso[0], iso[1]


def _week_label(key):
    """Human calendar date for an (iso_year, iso_week) key: the week's Monday,
    e.g. 'Aug 4'. Nobody thinks in ISO week numbers."""
    monday = datetime.date.fromisocalendar(key[0], key[1], 1)
    return f"{_MONTHS[monday.month - 1]} {monday.day}"


def timeline(metrics):
    """EQ as a function of time (ISO week), annotated with the operator's own
    fingerprint changes. Everyone iterates their stack; making those changes
    visible on the curve is how you attribute a move to a change instead of noise.
    """
    weeks = defaultdict(list)
    for m in metrics:
        if not m.get("day"):
            continue
        try:
            weeks[_iso_week(m["day"])].append(m)
        except Exception:
            continue
    rows, prev = [], None
    for key in sorted(weeks):
        cells = weeks[key]
        survc = sum(c["born"] - c["killed"] for c in cells)
        dollars = sum(c["dollars"] for c in cells)
        survkb = survc / 1024 if survc > 0 else 0.0
        eq = round(survkb / dollars, 4) if dollars else None
        fp = {"engine": modal([c["engine"] for c in cells]),
              "orchestrator": modal([c["model"] for c in cells]),
              "effort": modal([c["effort"] for c in cells])}
        changes = []
        if prev:
            for dim in ("engine", "orchestrator", "effort"):
                if fp[dim] != prev[dim]:
                    changes.append(f"{dim}: {prev[dim]} to {fp[dim]}")
        bs = babysitting(cells)
        rows.append({"week": _week_label(key), "eq": eq,
                     "sessions": len(cells), "fingerprint": fp, "changes": changes,
                     "babysitting": bs["per_100_turns"] if bs else None})
        prev = fp
    return rows


def babysitting(cells):
    """How much you had to babysit: interventions per 100 turns. nudge (you told
    it to continue) + interrupted (you had to stop it) + ends_q (it handed back on
    a question). Lower is better. This is the attention cost survKB/$ is blind to;
    it is reported beside the topline, not folded in (pricing your time against
    tokens is a separate, deliberate choice)."""
    turns = sum(m["n_turns"] for m in cells)
    if not turns:
        return None
    nudges = sum(m["nudges"] for m in cells)
    interrupts = sum(m["interrupts"] for m in cells)
    ends_q = sum(m["ends_q"] for m in cells)
    return {
        "per_100_turns": round(100 * (nudges + interrupts + ends_q) / turns, 2),
        "nudges": nudges, "interrupts": interrupts, "ends_q": ends_q,
        "turns": turns,
    }


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
    tline = timeline(metrics)
    bs = babysitting(metrics)

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
        "babysitting": bs,
        "lever": lever,
        "measure": measure,
        "timeline": tline,
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
    bs = report.get("babysitting")
    if bs:
        L.append("")
        L.append(f"**Babysitting: {bs['per_100_turns']} per 100 turns** "
                 f"({bs['nudges']} nudges, {bs['interrupts']} interrupts, "
                 f"{bs['ends_q']} hand-backs on a question). Lower is better. This "
                 f"is the attention cost the dollar number can't see; it is not "
                 f"folded into the topline.")
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
    tline = [r for r in report.get("timeline", []) if r["eq"] is not None]
    if len(tline) >= 2:
        L.append("## Your EQ over time")
        L.append("")
        L.append("By week. Each change you made is marked, so a move ties to a "
                 "change, not noise. Full annotated chart: report.html.")
        L.append("")
        hi = max(r["eq"] for r in tline) or 1.0
        for r in tline:
            fill = int(round(12 * r["eq"] / hi))
            bar = "█" * fill + "·" * (12 - fill)
            bsy = f" babysit={r['babysitting']}" if r.get("babysitting") is not None else ""
            note = ("  <- " + "; ".join(r["changes"])) if r["changes"] else ""
            L.append(f"`{r['week']:<7} {r['eq']:<7} {bar}{bsy}`{note}")
        L.append("")
    L.append("---")
    L.append("_Full vector, fingerprint, per-repo survival, claim verdicts, and "
             "confounds are in report.json. Open it only if you want the "
             "derivation._")
    L.append("")
    return "\n".join(L)


def render_html(report):
    """Self-contained, theme-aware chart of EQ over time, annotated with the
    operator's own fingerprint changes. Single series (blue), direct value
    labels, recessive grid, numbered change-flags, native SVG tooltips, table
    view. Stdlib string-building only, no external assets."""
    tl = [r for r in report.get("timeline", []) if r["eq"] is not None]
    eq0 = report["topline"]["eq"]
    esc = _html.escape
    head = (
        "<style>\n"
        ".viz-root{color-scheme:light;--surface:#fcfcfb;--ink:#0b0b0b;"
        "--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;"
        "--series:#2a78d6;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;"
        "background:var(--surface);color:var(--ink);padding:24px;border-radius:8px;}\n"
        "@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])) .viz-root{"
        "color-scheme:dark;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;"
        "--grid:#2c2c2a;--axis:#383835;--series:#3987e5;}}\n"
        ":root[data-theme=dark] .viz-root{color-scheme:dark;--surface:#1a1a19;--ink:#fff;"
        "--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--series:#3987e5;}\n"
        ".viz-root h1{font-size:20px;margin:0 0 2px;font-weight:600;}\n"
        ".viz-root p{color:var(--ink2);font-size:13px;margin:0 0 16px;}\n"
        ".viz-root svg{max-width:100%;height:auto;}\n"
        ".viz-root table{border-collapse:collapse;font-size:13px;margin-top:16px;"
        "font-variant-numeric:tabular-nums;}\n"
        ".viz-root th,.viz-root td{text-align:left;padding:4px 12px 4px 0;color:var(--ink2);"
        "border-bottom:1px solid var(--grid);}\n"
        ".viz-root th{color:var(--muted);font-weight:600;}\n"
        ".viz-root .flag{color:var(--series);font-weight:600;}\n"
        "</style>\n")
    if len(tl) < 2:
        body = (f'<div class="viz-root"><h1>{esc(str(eq0))} surviving KB per dollar</h1>'
                "<p>Not enough weeks of data to chart a trend yet.</p></div>")
        return _page(head + body)

    W, H = 760, 380
    ml, mr, mt, mb = 52, 24, 44, 52
    pw, ph = W - ml - mr, H - mt - mb
    eqs = [r["eq"] for r in tl]
    ylo, yhi = min(eqs), max(eqs)
    if yhi == ylo:
        yhi, ylo = yhi + 1, 0.0
    pad = (yhi - ylo) * 0.15
    ylo, yhi = ylo - pad, yhi + pad
    n = len(tl)

    def X(i):
        return ml + (pw * i / (n - 1) if n > 1 else pw / 2)

    def Y(v):
        return mt + ph * (1 - (v - ylo) / (yhi - ylo))

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="EQ over time">']
    # horizontal gridlines + y labels (3 ticks)
    for t in range(3):
        v = ylo + (yhi - ylo) * t / 2
        y = Y(v)
        parts.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{ml+pw}" y2="{y:.1f}" '
                     f'stroke="var(--grid)" stroke-width="1"/>')
        parts.append(f'<text x="{ml-8:.0f}" y="{y+4:.1f}" text-anchor="end" '
                     f'font-size="11" fill="var(--muted)">{v:.2f}</text>')
    # baseline
    parts.append(f'<line x1="{ml}" y1="{mt+ph}" x2="{ml+pw}" y2="{mt+ph}" '
                 f'stroke="var(--axis)" stroke-width="1"/>')
    # annotation flags (fingerprint changes): dashed verticals + numbered marks
    flags = []
    k = 0
    for i, r in enumerate(tl):
        if not r["changes"]:
            continue
        k += 1
        x = X(i)
        parts.append(f'<line x1="{x:.1f}" y1="{mt-6}" x2="{x:.1f}" y2="{mt+ph}" '
                     f'stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>')
        parts.append(f'<circle cx="{x:.1f}" cy="{mt-6}" r="8" fill="var(--surface)" '
                     f'stroke="var(--series)" stroke-width="1.5"/>')
        parts.append(f'<text x="{x:.1f}" y="{mt-2.5}" text-anchor="middle" '
                     f'font-size="10" font-weight="600" fill="var(--series)">{k}</text>')
        flags.append((k, r))
    # the line
    pts = " ".join(f"{X(i):.1f},{Y(r['eq']):.1f}" for i, r in enumerate(tl))
    parts.append(f'<polyline points="{pts}" fill="none" stroke="var(--series)" '
                 f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
    # points with native tooltips + direct value labels + x tick labels
    for i, r in enumerate(tl):
        x, y = X(i), Y(r["eq"])
        tip = f"{r['week']}: {r['eq']} survKB/$, {r['sessions']} sessions"
        if r["changes"]:
            tip += " | " + "; ".join(r["changes"])
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="var(--surface)" '
                     f'stroke="var(--series)" stroke-width="2"><title>{esc(tip)}</title></circle>')
        parts.append(f'<text x="{x:.1f}" y="{y-10:.1f}" text-anchor="middle" '
                     f'font-size="10" fill="var(--ink2)">{r["eq"]:.2f}</text>')
        parts.append(f'<text x="{x:.1f}" y="{mt+ph+16:.0f}" text-anchor="middle" '
                     f'font-size="10" fill="var(--muted)">{esc(r["week"])}</text>')
    parts.append("</svg>")

    rows = "".join(
        f"<tr><td>{esc(r['week'])}</td><td>{r['eq']}</td><td>{r['sessions']}</td>"
        f"<td>{esc('; '.join(r['changes']) or '')}</td></tr>" for r in tl)
    legend = ""
    if flags:
        items = "".join(f'<li><span class="flag">{k}</span> {esc(r["week"])}: '
                        f'{esc("; ".join(r["changes"]))}</li>' for k, r in flags)
        legend = (f'<p style="margin-top:12px"><strong>Your changes:</strong></p>'
                  f'<ol style="font-size:13px;color:var(--ink2);margin:4px 0">{items}</ol>')
    body = (f'<div class="viz-root"><h1>{esc(str(eq0))} surviving KB per dollar</h1>'
            f'<p>Higher is better. Each numbered flag is a change you made to your '
            f'setup, so a move on the curve ties to a change, not noise.</p>'
            f'{"".join(parts)}{legend}'
            f'<table><thead><tr><th>week</th><th>EQ</th><th>sessions</th>'
            f'<th>changes</th></tr></thead><tbody>{rows}</tbody></table></div>')
    return _page(head + body)


def _page(inner):
    return ("<!doctype html><html><head><meta charset=utf-8>"
            "<meta name=viewport content=\"width=device-width,initial-scale=1\">"
            "<title>Dyno: your efficiency over time</title></head>"
            f"<body>{inner}</body></html>\n")


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
    with open(os.path.join(args.out, "report.html"), "w") as f:
        f.write(render_html(report))
    print(os.path.join(args.out, "report.json"))


if __name__ == "__main__":
    main()
