#!/usr/bin/env python3
# REFERENCE BUILD. Source of truth: vibrant_report.spec.md (what it must do)
# + test_vibrant_report.py (the verification). Code is a regenerable artifact:
# rebuild it from the spec and the acceptance test must still pass. See SOURCE.md.
"""
vibrant_report.py, the turn-key driver behind the vibrant-report skill.

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
  vibrant_report --harness claude-code --repos <path>[,<path>...] \
      --snapshot <dir> [--since <git-approxidate>] [--frontier <path>] \
      [--now <epoch>] --out <dir>

Stdlib only. Deterministic: same (snapshot, git HEADs, frontier, since) inputs
give byte-identical report.json regardless of the model that invoked it.
"""
import argparse
import concurrent.futures
import datetime
import glob
import hashlib
import time
import html as _html
import json
import math
import os
import re
import sys
import urllib.request
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "core"))

import survival_git  # noqa: E402  (core/survival_git.py, after path insert)
import horizon_attribute  # noqa: E402  (core/horizon_attribute.py, the commit<->session join)
import som_merge  # noqa: E402  (core/som_merge.py, the federated shared-map merge)

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


def blend(values):
    """The distribution of a dimension across sessions, most-common first:
    [{value, sessions, share}]. This is how a stack is described by its arms rather
    than collapsed to one modal label (a 46/36/18 solo/delegate/workflow stack is
    'blended', not 'solo')."""
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    total = sum(counts.values()) or 1
    return [{"value": k, "sessions": counts[k], "share": round(100 * counts[k] / total, 1)}
            for k in sorted(counts, key=lambda k: (-counts[k], str(k)))]


def _arm(values):
    """One fingerprint arm: its blend, the plurality value, and whether the stack is
    genuinely blended on this axis (no value holds a clear majority)."""
    b = blend(values)
    return {"blend": b, "dominant": b[0]["value"] if b else None,
            "is_blended": len(b) > 1 and b[0]["share"] < 60.0}


def engine_of(sess):
    if (sess.get("workflows") or 0) > 0 or (sess.get("wf_agents") or 0) > 0:
        return "workflow"
    if (sess.get("plain_agents") or 0) > 0:
        return "delegate"
    return "solo"


def routing_of(sess):
    """Model routing (taxonomy dim 2), countable so it stays deterministic: do the
    worker models differ from the orchestrator's? 'none' (no workers) /
    'homogeneous' (workers share the orchestrator's family) / 'cross-family'."""
    submix = sess.get("submix") or {}
    if not submix:
        return "none"
    orch = base_model(sess.get("model"))
    worker_bases = {base_model(m) for m in submix}
    return "homogeneous" if worker_bases == {orch} else "cross-family"


def worker_of(sess):
    """The dominant WORKER model a session dispatches to, base-family, weighted by
    subagent invocation count; 'solo' when it runs no workers. This is the 'who does
    the work' half of the rig, distinct from the orchestrator ('who drives'). The
    same model reads completely differently as a driver vs a worker, which is exactly
    the distinction a per-orchestrator-only view collapses."""
    submix = sess.get("submix") or {}
    if not submix:
        return "solo"
    top = sorted(submix, key=lambda k: (-submix[k], k))[0]
    return base_model(top)


def roles_of(sess):
    """The rig's model configuration as one arm: orchestrator -> dominant worker,
    e.g. 'opus-4-8 -> opus-5' (opus-4-8 drives, dispatches opus-5 workers) vs
    'opus-5 -> sonnet-5' (opus-5 drives). A first-class parametrix axis: the pairing
    is the rig, not the driver alone."""
    return f"{base_model(sess.get('model'))} -> {worker_of(sess)}"


def rig_key(m):
    """The deterministic fingerprint skeleton a session belongs to: engine /
    routing / effort. The classifier labels distinct RIGS, not sessions (the
    dedup decision), so this is the join key between a session and its
    fingerprint-labels entry. Pure function of already-computed fields."""
    return f"{m['engine']}/{m['routing']}/{m['effort']}"


PATTERN_DIMS = ("fine_topology", "review_regime", "knowledge_practice")


def load_labels(labels_path):
    """Load the fingerprint-labels cache: {rig_key: {fine_topology, review_regime,
    knowledge_practice}}. Returns {} if absent. Labels-only, operator-correctable;
    the driver consumes them but never computes them (the determinism invariant:
    pattern classification is the in-session model's job, cached here)."""
    if not labels_path or not os.path.exists(labels_path):
        return {}
    try:
        data = json.load(open(labels_path))
    except Exception:
        return {}
    return data.get("rigs") or {}


def attach_labels(metrics, labels):
    """Attach the three pattern-dimension labels to each session by its rig key.
    Absent cache or absent rig -> 'unclassified' (the pending slot survives)."""
    for m in metrics:
        rig = labels.get(rig_key(m), {})
        for dim in PATTERN_DIMS:
            m[dim] = rig.get(dim, "unclassified")


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


def load_frontier(path_or_url):
    """Load a frontier from a path or a URL (http/https/file). Returns (dict, raw
    bytes). The URL form is the federated read side: compare against a team's or the
    public frontier without cloning it. Anything unfetchable/unreadable degrades to
    an empty frontier, never an error, so a run always produces a number."""
    ref = path_or_url or ""
    try:
        if re.match(r"^(https?|file)://", ref):
            with urllib.request.urlopen(ref, timeout=30) as r:  # noqa: S310
                raw = r.read()
        elif ref and os.path.exists(ref):
            raw = open(ref, "rb").read()
        else:
            return {"entries": []}, b""
        return json.loads(raw), raw
    except Exception:
        return {"entries": []}, b""


def load_misery(snapshot_dir, path=None):
    """Load the misery cache: {sid: {score, tags, evidence}} (schema vibrant/misery@1).
    The inference layer (the skill's Haiku->Sonnet cascade) writes it out of band;
    the driver consumes it as a pure function, so the report stays deterministic. An
    absent cache yields {} and a no-misery run, leaving the efficiency meter untouched.
    Default location: alongside the snapshot."""
    p = path or os.path.join(snapshot_dir, "misery-cache.json")
    if not os.path.exists(p):
        return {}
    try:
        d = json.load(open(p))
    except Exception:
        return {}
    return d.get("sessions", {}) if isinstance(d, dict) else {}


def load_som(snapshot_dir, path=None):
    """Load the SOM cache: {schema, lattice, sessions: [{sid, day, bmu, qe}]}
    (schema vibrant/som@1). The trainer writes it out of band; the driver
    consumes it as a pure function, so the report stays deterministic. An
    absent or invalid cache yields {} and a no-SOM run, leaving rig_space's
    hand-written trajectory untouched. Default location: alongside the
    snapshot."""
    p = path or os.path.join(snapshot_dir, "som-cache.json")
    if not os.path.exists(p):
        return {}
    try:
        d = json.load(open(p))
    except Exception:
        return {}
    if not isinstance(d, dict) or d.get("schema") != "vibrant/som@1":
        return {}
    return d


def load_shared_map(snapshot_dir, path=None):
    """Load a published federated shared map: {schema vibrant/som-merged@1, lattice,
    field, weight, support, contributors, ...}, the peer-validated cost field merged
    across operators (core/som_merge.merge). The commons produces it out of band and an
    operator drops it beside their snapshot; the driver consumes it as a pure function.
    Absent or invalid yields {} and no shared-map section. Default location: alongside
    the snapshot."""
    p = path or os.path.join(snapshot_dir, "shared-map.json")
    if not os.path.exists(p):
        return {}
    try:
        d = json.load(open(p))
    except Exception:
        return {}
    if not isinstance(d, dict) or d.get("schema") != "vibrant/som-merged@1":
        return {}
    return d


def _misery_by(metrics, dim):
    """Mean misery per cell of one fingerprint dimension: {value: mean_misery}.
    Misery is a meter over the SAME parameter space as efficiency, so it slices by
    every arm the efficiency meter does. Sessions with no score are ignored."""
    g = defaultdict(list)
    for m in metrics:
        if m.get("misery") is not None:
            g[m.get(dim, "unknown")].append(m["misery"])
    return {k: round(sum(v) / len(v), 1) for k, v in sorted(g.items())}


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
    # fan-out width (deterministic topology sub-signal): subagents dispatched
    fanout = (sess.get("wf_agents") or 0) + (sess.get("plain_agents") or 0)
    effort = modal([t.get("effort") for t in T if t.get("effort")])
    c = code.get(sid) or {}
    orch_out = usage_field(c.get("orch") or {}, "out") if usage_field \
        else (c.get("orch") or {}).get("out_tok", 0)
    dollars = session_cost(sess) if session_cost else 0.0
    return {
        "sid": sid,
        "day": sess.get("day"),
        "proj": sess.get("proj") or "",
        "engine": engine_of(sess),
        "routing": routing_of(sess),
        "model": base_model(sess.get("model")),
        "worker": worker_of(sess),
        "model_roles": roles_of(sess),
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
        "fanout": fanout,
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


_SIMPLICITY_D0 = 100.0  # decision-points-per-1000-lines where simplicity is 100/e; the
# half-simplicity point is ~69/1000 lines. A fixed anchor so scores compare across reports.


def _density_simplicity(density, d0=_SIMPLICITY_D0):
    """Map a complexity DENSITY (decision points per 1000 surviving lines) to a 0..100
    simplicity score, higher = simpler. A smooth exponential 100 * e^(-density/d0): density
    0 (straight-line code) -> 100, and it decays as the surviving code gets denser/branchier.
    None when there is no surviving code to measure. This is a STOCK property of the code the
    setup left behind, distinct from bloat (a per-change flow); see docs/claims.md."""
    if density is None or density < 0:
        return None
    return round(100.0 * math.exp(-density / d0), 1)


def _surviving_lines(cx, surviving):
    """Guard for per-config/per-period density: complexity per 1000 surviving lines, or None
    when nothing survives (a config that shipped nothing durable has no density to score)."""
    if not surviving or cx is None:
        return None
    return cx / surviving * 1000.0


def topline(metrics, numerator, denom_metrics=None):
    """The one meter, LARGER IS BETTER: surviving functionality per Mtok.

    Functionality = surviving complexity (git decision points, a proxy for how
    much real logic you built and kept). Fuel = total tokens processed. Burning
    tokens for no lasting functionality lowers it -- the inversion of naive
    tokenmaxxing, where more tokens 'won'. DORA change failure rate rides
    alongside as the delivery-quality lens. surviving-KB and dollars are kept as
    depth lenses (and drive the engine-efficiency lever).

    `denom_metrics` is the git<->session-scoped subset whose output tokens buy the
    numerator's functionality (sessions that worked the measured repos). It scopes
    only the fuel denominator; the depth lenses stay over the whole window."""
    denom = metrics if denom_metrics is None else denom_metrics
    survc = sum(m["born"] - m["killed"] for m in metrics)
    survkb = survc / 1024 if survc > 0 else 0.0
    dollars = sum(m["dollars"] for m in metrics)
    # Fuel = OUTPUT tokens (what the model generates), not total tokens: total is
    # ~97% cache-reads, which drown the signal and are near-free on a subscription.
    # Output is the scarce, generative fuel, and dividing by it penalizes verbosity
    # (a chatty model burns output for the same logic and scores lower). Scoped to
    # the sessions that produced the functionality (the git<->session join), so the
    # denominator is not inflated by fuel spent in repos we did not measure.
    out_mtok = sum(m["out_tok"] for m in denom) / 1e6
    total_mtok = sum(m["in_tok"] + m["cache_r"] + m["cache_w"] + m["out_tok"]
                     for m in denom) / 1e6
    # functionality = DURABLE shipped complexity: decision points that landed in
    # non-reverted commits and still survive at HEAD. Falls back to raw surviving
    # complexity only if the durable cut was not computed (e.g. a caller that did
    # not run shipped_by_day). This is what makes the meter track shipped work, not
    # in-chat verbosity: a rig that generates a mountain but commits little that
    # sticks scores low.
    # FUNCTION, not complexity: count the durable shipped changes (units of work that
    # landed and were not reverted). Complexity is a COST, not the value: a model that
    # over-engineers packs more decision-points into each change and would inflate a
    # complexity numerator, so complexity-per-token rewarded exactly that. Counting
    # the changes themselves is over-engineering-resistant. Complexity moves to a
    # BLOAT meter (per change) where over-engineering is exposed, not rewarded.
    functionality = numerator.get("durable_changes", numerator.get("total_changes", 0))
    dcx = numerator.get("durable_complexity", numerator.get("net_complexity", 0))
    # eq is now the CONTINUOUS numerator: surviving FUNCTIONALITY (durable decision points
    # that stuck) per Mtok. It replaces the count of durable changes as the base measure,
    # because a count is a team convention (commit/PR granularity) and fragile to tiny-sample
    # lucky units, so it does not survive unseen data or stay comparable on the frontier. The
    # count rides alongside as change_throughput. Over-engineering is guarded by the
    # simplicity (density) axis, so a continuous functionality numerator is safe. See X5.
    change_throughput = round(functionality / out_mtok, 2) if out_mtok else None
    eq = round(dcx / out_mtok, 1) if out_mtok else None
    # bloat stays as a change-discipline meter (decision points per shipped change), but it
    # is NOT simplicity: it is blind to code density and, like efficiency, rewards making
    # more changes. simplicity is now a STOCK measure of the surviving code's density.
    bloat = round(dcx / functionality, 1) if functionality else None
    # simplicity: how simple the surviving code actually is, measured as its complexity
    # DENSITY (decision points per 1000 surviving lines) mapped to 0..100, higher = simpler.
    # Independent of bloat (two configs with the same bloat can differ 7x in density), and
    # counterbalanced by efficiency: padding lines to lower density costs output tokens, so
    # efficiency penalises the one way to game it. See _density_simplicity and docs/claims.md.
    density = numerator.get("complexity_per_1k_lines")
    if density is None:
        surv_lines = numerator.get("total_surviving", 0)
        density = (numerator.get("net_complexity", 0) / surv_lines * 1000) if surv_lines else None
    simplicity = _density_simplicity(density)
    # PARALLEL numerator for the count-vs-continuous comparison: surviving FUNCTIONALITY
    # (durable decision points that stuck) per Mtok, a CONTINUOUS measure blind to how the
    # work was chopped into sessions/commits/PRs. eq (count of durable changes) is fragile
    # to convention (commit granularity) and to tiny-sample lucky units; eq_continuous is
    # not. Carried alongside eq so both accrue on the frontier and the data can adjudicate
    # which is the stabler efficiency numerator across unseen teams. See docs/claims.md X5.
    return {"eq": eq,
            "unit": "surviving decision points per Mtok output",
            "larger_is_better": True,
            "functionality": functionality,  # durable changes (count), retained for reference
            "change_throughput": change_throughput,  # count numerator, no longer the base
            "bloat": bloat,  # decision points per shipped change; a change-discipline meter
            "complexity_density": density,  # decision points per 1000 surviving lines
            "simplicity": simplicity,  # density mapped to 0..100, higher = simpler code
            "output_mtok": round(out_mtok, 3),
            "total_mtok": round(total_mtok, 3),
            "denominator_sessions": len(denom),
            "change_failure_rate": numerator.get("change_failure_rate"),
            "surv_kb": round(survkb, 2), "dollars": round(dollars, 2),
            "sessions": len(metrics), "_survkb": survkb, "_dollars": dollars}


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _iso_week(day):
    y, m, d = (int(x) for x in day.split("-")[:3])
    iso = datetime.date(y, m, d).isocalendar()
    return iso[0], iso[1]


def _bucket(day, gran):
    """Time-bucket key + human label for a YYYY-MM-DD day at a granularity."""
    if gran == "month":
        return day[:7], day[:7]
    if gran == "day":
        return day, _daylabel(day)
    key = _iso_week(day)
    return f"{key[0]}-{key[1]:02d}", _week_label(key)


def _daylabel(day):
    y, m, d = (int(x) for x in day.split("-")[:3])
    return f"{_MONTHS[m - 1]} {d}"


def fuel_and_work(metrics, gran="week"):
    """The core chart data: the fuel trio (read, cache-read, output tokens) and
    the work (net code retained, KB) per time bucket. Different scales by design,
    so the surface renders them as aligned small multiples, never one axis."""
    buckets = {}
    order = []
    for m in metrics:
        if not m.get("day"):
            continue
        try:
            key, label = _bucket(m["day"], gran)
        except Exception:
            continue
        if key not in buckets:
            buckets[key] = {"bucket": label, "read_tok": 0, "cache_read_tok": 0,
                            "cache_write_tok": 0, "output_tok": 0, "surv_kb": 0.0}
            order.append(key)
        b = buckets[key]
        b["read_tok"] += m["in_tok"]
        b["cache_read_tok"] += m["cache_r"]
        b["cache_write_tok"] += m["cache_w"]
        b["output_tok"] += m["out_tok"]
        survc = m["born"] - m["killed"]
        b["surv_kb"] += survc / 1024 if survc > 0 else 0.0
    rows = [buckets[k] for k in sorted(order)]
    for r in rows:
        r["surv_kb"] = round(r["surv_kb"], 1)
    return rows


def fuel_sliced(metrics, gran, dim):
    """The fuel-and-work series cut by a fingerprint dimension (model / effort /
    engine): {dim_value: [buckets...]}. Session-side only -- tokens and same-
    session survival, no git join needed. This is how you watch one model's token
    towers against the work they bought, next to another's."""
    groups = defaultdict(list)
    for m in metrics:
        groups[m.get(dim, "unknown")].append(m)
    return {k: fuel_and_work(v, gran) for k, v in sorted(groups.items())}


def _week_label(key):
    """Human calendar date for an (iso_year, iso_week) key: the week's Monday,
    e.g. 'Aug 4'. Nobody thinks in ISO week numbers."""
    monday = datetime.date.fromisocalendar(key[0], key[1], 1)
    return f"{_MONTHS[monday.month - 1]} {monday.day}"


def detect_changes(metrics, window=14, sustain=0.75):
    """The operator's real setup changes, dated to the day they happened.

    Falsifiable claims are fatal: the operator knows exactly when they switched, so
    a wrong date is an instant discredit. Week-granular detection cannot do this (it
    reports the week's Monday and lags a real mid-week switch by up to a week). This
    works at the day level: a change is a value becoming the day-MAJORITY (>50% of
    that day's sessions) and holding it as a sustained era (the day-majority on at
    least `sustain` of the next `window` days that have a majority). A genuinely
    blended dimension (engine, when the operator alternates and no day holds a
    majority, or the majority wobbles) yields NO changes rather than inventing them.
    Returns [{date, dim, from, to}], sorted."""
    by_day = defaultdict(list)
    for m in metrics:
        if m.get("day"):
            by_day[m["day"]].append(m)
    days = sorted(by_day)
    out = []
    for label, field in (("engine", "engine"), ("orchestrator", "model"),
                         ("worker", "worker"), ("effort", "effort")):
        daymaj = {}
        for day in days:
            vals = [c.get(field) for c in by_day[day]
                    if c.get(field) not in (None, "unknown", "none")]
            b = blend(vals)
            daymaj[day] = b[0]["value"] if b and b[0]["share"] > 50.0 else None
        regime = None
        for i, day in enumerate(days):
            v = daymaj[day]
            if v is None:
                continue
            if regime is None:
                regime = v
                continue
            if v != regime:
                nxt = [daymaj[x] for x in days[i:i + window] if daymaj.get(x) is not None]
                if len(nxt) >= max(3, window // 2) and \
                        sum(1 for x in nxt if x == v) / len(nxt) >= sustain:
                    out.append({"date": day, "dim": label, "from": regime, "to": v})
                    regime = v
    return sorted(out, key=lambda c: c["date"])


def timeline(metrics, all_fp=None, gran="week", shipped=None, complexity=None,
             out_by_day=None):
    """Efficiency curve (surviving KB per Mtok output, the headline's unit) binned at
    `gran` (day / week / month), annotated with the operator's real, day-dated setup
    changes (detect_changes) and their VELOCITY (shipped changes, from `shipped`, a
    {day: count} map). A change flag sits on the bucket that contains its date and
    carries the exact date, so the claim is checkable.

    The curve uses `metrics` (survival-having sessions, since EQ needs survival), but
    change detection uses `all_fp`, the day/engine/model/effort of EVERY session, so
    a model switch is dated over all runs (not just the ones that wrote surviving
    code) and matches the day the operator actually switched."""
    buckets, labels = defaultdict(list), {}
    for m in metrics:
        if not m.get("day"):
            continue
        try:
            k, lab = _bucket(m["day"], gran)
        except Exception:
            continue
        buckets[k].append(m)
        labels[k] = lab
    chg = defaultdict(list)
    for c in detect_changes(all_fp if all_fp is not None else metrics):
        try:
            k, _ = _bucket(c["date"], gran)
        except Exception:
            continue
        chg[k].append(f'{c["dim"]}: {c["from"]} to {c["to"]} ({_daylabel(c["date"])})')
    ship, cxb = defaultdict(int), defaultdict(int)
    for day, cnt in (shipped or {}).items():
        try:
            k, _ = _bucket(day, gran)
        except Exception:
            continue
        ship[k] += cnt
    for day, cx in (complexity or {}).items():
        try:
            k, _ = _bucket(day, gran)
        except Exception:
            continue
        cxb[k] += cx
    # scoped denominator: output tokens of the sessions that worked the measured
    # repos, bucketed by day, so the chart's eq matches the headline (which scopes
    # the same way) and is not diluted by fuel spent in repos we did not measure.
    obk = defaultdict(float)
    for day, ot in (out_by_day or {}).items():
        try:
            k, _ = _bucket(day, gran)
        except Exception:
            continue
        obk[k] += ot
    rows = []
    for k in sorted(buckets):
        cells = buckets[k]
        born = sum(c["born"] for c in cells)
        killed = sum(c["killed"] for c in cells)
        survc = born - killed
        survkb = survc / 1024 if survc > 0 else 0.0
        # denominator: scoped output (measured-repo sessions) when provided, else all
        # cells' output. eq is the HEADLINE measure: surviving FUNCTIONALITY (durable
        # decision points that landed and stuck) per Mtok output, a CONTINUOUS numerator
        # blind to how the work was chopped into commits/PRs; the count of durable changes
        # rides alongside as `shipped`. survkb stays a depth field.
        out_mtok = (obk.get(k, 0.0) if out_by_day is not None
                    else sum(c["out_tok"] for c in cells)) / 1e6
        eq = round(cxb.get(k, 0) / out_mtok, 1) if out_mtok else None
        fp = {"engine": modal([c["engine"] for c in cells]),
              "orchestrator": modal([c["model"] for c in cells]),
              "effort": modal([c["effort"] for c in cells])}
        bs = babysitting(cells)
        # Companions to eq, carried per bucket:
        #  complexity = durable shipped decision points (the eq numerator).
        #  shipped    = durable shipped changes (throughput / velocity).
        #  churn      = share of written code deleted in-session; ambiguous (an
        #               orchestrator discarding bad worker output is healthy), so it
        #               rides as data, not a verdict.
        mis = [c["misery"] for c in cells if c.get("misery") is not None]
        rows.append({"week": labels[k], "eq": eq,
                     "sessions": len(cells), "fingerprint": fp,
                     "changes": chg.get(k, []), "born": born, "killed": killed,
                     "complexity": cxb.get(k, 0), "shipped": ship.get(k, 0),
                     "out_mtok": round(out_mtok, 4),
                     "churn_pct": round(100 * killed / born, 1) if born else None,
                     "misery": round(sum(mis) / len(mis), 1) if mis else None,
                     "babysitting": bs["per_100_turns"] if bs else None})
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


def fingerprint_summary(metrics, numerator):
    """The rig as one point in the taxonomy's six dimensions (docs/taxonomy.md).
    Harness-neutral by construction: it reads the generic per-session fields, not
    anything Claude-Code-specific. Deterministic dimensions are filled; the
    pattern dimensions (fine topology, review regime, knowledge practice) carry a
    'pending-classification' slot the in-session LLM classifier fills -- keeping
    the tool self-bootstrapping (no API key, no install)."""
    if not metrics:
        return None
    fanouts = [m["fanout"] for m in metrics if m.get("fanout")]
    pending = "pending-classification (LLM; see docs/taxonomy.md)"

    def label(dim):
        """Modal label for a pattern dimension, or the pending slot when the
        labels cache did not classify this rig (modal == 'unclassified')."""
        v = modal([m.get(dim, "unclassified") for m in metrics])
        return pending if v == "unclassified" else v

    fine, review, knowledge = (label(d) for d in PATTERN_DIMS)
    ingested = ["topology", "routing", "orchestrator-model", "worker-model",
                "model-roles", "effort", "delivery-cadence"]
    for name, val in (("fine-topology", fine), ("review-regime", review),
                      ("knowledge-practice", knowledge)):
        if val != pending:
            ingested.append(name)
    # Countable dims are reported as their blend (the arms of the stack), not one
    # modal label: a blended setup should not read as a single engine/model/effort.
    topo = _arm([m["engine"] for m in metrics])
    topo["fanout_width_mean"] = round(sum(fanouts) / len(fanouts), 1) if fanouts else 0
    topo["fine"] = fine
    return {
        "orchestration_topology": topo,
        "model_routing": _arm([m["routing"] for m in metrics]),
        "orchestrator_model": _arm([m["model"] for m in metrics]),
        "worker_model": _arm([m["worker"] for m in metrics]),
        "model_roles": _arm([m["model_roles"] for m in metrics]),
        "reasoning_effort": _arm([m["effort"] for m in metrics]),
        "review_regime": review,
        "knowledge_practice": knowledge,
        "delivery_cadence": {
            "change_failure_rate": numerator.get("change_failure_rate")},
        "ingested_dimensions": ingested,
    }


def frontier_eq(entry):
    d = (entry.get("vector") or {}).get("dollars_per_survkb")
    return (1.0 / d) if d else None


def _rig_objective_metrics(metrics, attribution, misery_block):
    """Per rig (model_roles): the three objectives the descent can optimize, grounded
    in the by-rig git attribution so each SOM cell inherits its dominant setup's
    numbers. efficiency = surviving decision points per Mtok output (continuous, with the
    change count alongside as eff_count); simplicity = the complexity DENSITY
    of that rig's surviving code (decision points per 1000 surviving lines) mapped to
    0..100; flow = 100 - misery. Any may be None when its input is missing."""
    out_by = defaultdict(float)
    for m in metrics:
        out_by[m.get("model_roles")] += m.get("out_tok", 0)
    cx = (attribution or {}).get("by_model_roles") or {}
    mis = (misery_block or {}).get("by_model_roles") or {}
    stats = {}
    for rig, v in cx.items():
        om = out_by.get(rig, 0) / 1e6
        commits = v.get("commits", 0)
        ncx = v.get("net_complexity", 0)
        m_ = mis.get(rig)
        stats[rig] = {
            # eff is the CONTINUOUS numerator (surviving decision points per Mtok), blind to
            # commit/PR granularity; the count rides alongside as eff_count.
            "eff": round(ncx / om, 1) if om else None,
            "eff_count": round(commits / om, 2) if om else None,
            "simp": _density_simplicity(_surviving_lines(ncx, v.get("surviving", 0))),
            "flow": round(100 - m_, 1) if m_ is not None else None}
    return stats


def rig_stats(metrics, attribution, misery_block):
    """Per rig-config (orchestrator -> worker): efficiency (durable complexity per
    Mtok output), misery, and session count, from the operator's OWN data. This is
    the navigation surface: where each of your configurations actually sits."""
    out_by, n_by = defaultdict(float), defaultdict(int)
    for m in metrics:
        out_by[m["model_roles"]] += m["out_tok"]
        n_by[m["model_roles"]] += 1
    cx = (attribution or {}).get("by_model_roles") or {}
    mis = (misery_block or {}).get("by_model_roles") or {}
    stats = {}
    for rig, v in cx.items():
        om = out_by.get(rig, 0) / 1e6
        stats[rig] = {"rig": rig, "eff": round(v["net_complexity"] / om, 1) if om else 0.0,
                      "misery": mis.get(rig), "sessions": n_by.get(rig, 0),
                      "commits": v.get("commits", 0)}
    return stats


# the fingerprint axes the recommendation descends over, each as (label, the
# per-session metric field, the attribution key, the misery-block key). Topology is
# deliberately NOT here: delegation buys throughput and scale (the operator uses it
# to build large systems in parallel), so "go solo" is never a cost-optimization
# move, it trades away the reason they delegate. The cost knobs are model + effort.
_GRAD_DIMS = [
    ("orchestrator", "model", "by_orchestrator", "by_model"),
    ("worker", "worker", "by_worker", "by_worker"),
    ("effort", "effort", "by_effort", "by_effort"),
]


def gradient_move(metrics, attribution, misery_block, min_sessions=8, misery_tol=4.0):
    """The recommendation as gradient descent over the fingerprint. The objective is
    the TRUE economy, dollars per 1k surviving decision points (which prices model
    heterogeneity and the orchestrator's dominant cache-read cost, so it is not fooled
    by the opus-drives-sonnet false economy that per-token efficiency falls for). For
    every axis, it measures the cost at each value from the operator's OWN runs, takes
    the steepest single-axis descent from the value they use most to the cheapest one
    that is not more miserable, and returns the axis with the largest drop. Never the
    frontier; never an axis they already optimize (a maxed axis has no cheaper value)."""
    attribution = attribution or {}
    misery_block = misery_block or {}
    best = None
    for label, mfield, akey, mis_key in _GRAD_DIMS:
        # count of durable shipped changes (function), NOT complexity: complexity is
        # bloat, and dividing dollars by it would reward over-engineering.
        chg = {k: v["commits"] for k, v in (attribution.get(akey) or {}).items()}
        mis = misery_block.get(mis_key) or {}
        dol, sess = defaultdict(float), defaultdict(int)
        for m in metrics:
            v = m.get(mfield)
            dol[v] += m.get("dollars", 0.0)
            sess[v] += 1
        # cost = dollars per shipped change, per value with enough evidence
        cost = {v: dol[v] / chg[v]
                for v in chg if chg[v] > 0 and sess[v] >= min_sessions and dol[v] > 0}
        if len(cost) < 2:
            continue
        dominant = max(cost, key=lambda v: sess[v])
        dcost, dmis = cost[dominant], mis.get(dominant)
        # candidates: cheaper, enough evidence, and not more miserable than today
        cands = [v for v in cost if v != dominant and cost[v] < dcost
                 and (dmis is None or mis.get(v) is None or mis[v] <= dmis + misery_tol)]
        if not cands:
            continue
        to = min(cands, key=lambda v: cost[v])
        drop = dcost - cost[to]
        cand = {"axis": label, "from": dominant, "to": to,
                "from_cost": round(dcost, 1), "to_cost": round(cost[to], 1),
                "savings_pct": round(100 * drop / dcost, 0),
                "from_sessions": sess[dominant], "to_sessions": sess[to],
                "from_misery": dmis, "to_misery": mis.get(to),
                "tweak": f"Run your {label} at {to} instead of {dominant}.",
                "_drop": drop}
        if best is None or cand["_drop"] > best["_drop"]:
            best = cand
    if best:
        best.pop("_drop", None)
    return best


# ---------------------------------------------------------------------------
# rig_space: the fingerprint as a position in a collapsed latent space, moving
# over time. Full design + attribution (PAD / ALMA) in rig_space.spec.md. This is
# the HAND-WRITTEN embedding (stdlib, deterministic, computed inline). The learned
# SOM-on-the-commons version is future work and would land behind a coordinate
# cache, the same out-of-band seam misery and the fingerprint labels use.

# Each arm value's pre-placed position on the three latent axes, in [0, 1].
# fan_out: how much you parallelize. firepower: model tier and its cost.
# rigor: review intensity. Monotonic by construction (see the spec's acceptance).
_FAN = {"solo": 0.0, "delegate": 0.5, "workflow": 1.0}
_FIRE = {"haiku-4-5": 0.15, "haiku-4-5-20251001": 0.15, "fable-5": 0.25,
         "sonnet-4-6": 0.55, "sonnet-5": 0.6, "opus-4-6": 0.85, "opus-4-8": 0.9,
         "opus-5": 1.0}
_RIGOR = {"none": 0.0, "manual": 0.2, "automated": 0.35, "agentic-review-pass": 0.6,
          "sweeps": 0.7, "spec-and-acceptance": 0.8, "cross-model": 0.9}
RIG_AXES = ("fan_out", "firepower", "rigor")

# velocity-response scalars: session is the raw input (velocity 1); mood chases the
# session point; personality chases the mood, slower. session > mood > personality.
V_MOOD = 0.25
V_PERS = 0.04


def _embed(m):
    """Collapse a session's arms to a point in the 3-axis latent space, each in
    [0,1]. Hand-written and deterministic (no model, no cache): a pure function of
    the session's fingerprint arms."""
    fan = _FAN.get(m.get("engine"), 0.5)
    orch = _FIRE.get(m.get("model"), 0.5)
    wk = m.get("worker")
    fire = orch * 0.6 + _FIRE.get(wk, 0.5) * 0.4 if (wk and wk != "solo") else orch
    rr = (m.get("review_regime") or "").replace(" ", "-")
    rigor = _RIGOR.get(rr, 0.35)  # unclassified -> automated baseline, so the axis
    return (round(fan, 4), round(fire, 4), round(rigor, 4))  # still computes


def _layered_trajectory(points):
    """Run the layered update over the ordered session points: mood chases each
    session point at V_MOOD, personality chases mood at V_PERS (the PAD/ALMA cascade,
    pure vector math). Returns (mood, personality, path) where path is the mood
    position after each session. Deterministic given the points and the constants."""
    mood = list(points[0])
    pers = list(points[0])
    path = []
    for p in points:
        for k in range(len(mood)):
            mood[k] += V_MOOD * (p[k] - mood[k])
            pers[k] += V_PERS * (mood[k] - pers[k])
        path.append(tuple(round(x, 4) for x in mood))
    return (tuple(round(x, 4) for x in mood), tuple(round(x, 4) for x in pers), path)


def _downsample(seq, cap):
    """Even-stride downsample to at most `cap` items, always keeping the last."""
    if len(seq) <= cap:
        return list(seq)
    step = len(seq) / cap
    idx = sorted({int(i * step) for i in range(cap)} | {len(seq) - 1})
    return [seq[i] for i in idx]


def _drift_path(cells, days, response=0.20, cap=14):
    """The smoothed mood path over the ordered session cells. Per-session BMUs jump
    (fast noise); the mood chases them at `response` so the line is a gentle drift
    (the signal), the same fast/slow split as _layered_trajectory. Returns
    [{"day", "pos": [r, c]}] in float lattice coordinates, downsampled. Deterministic."""
    if not cells:
        return []
    pos = [float(cells[0][0]), float(cells[0][1])]
    out = []
    for (r, c), day in zip(cells, days):
        pos[0] += response * (r - pos[0])
        pos[1] += response * (c - pos[1])
        out.append({"day": day, "pos": [round(pos[0], 3), round(pos[1], 3)]})
    return _downsample(out, cap)


def som_map(metrics, som_cache, move, field_window_days=14, now_day=None,
            attribution=None, misery_block=None):
    """The learned-map consumer (som_consume.spec.md): joins the trained SOM's
    per-session BMU coordinates to the driver's metrics, and turns the join into
    a trajectory across the lattice, a time-windowed descriptive field
    (d_per_survkb per cell), and the arm-change gradient projected onto the map.
    Pure function; no training, no numpy. None when the cache is empty or joins
    nothing (the caller falls back to the hand-written rig_space trajectory)."""
    if not som_cache:
        return None
    lattice = som_cache.get("lattice") or {}
    rows, cols = lattice.get("rows"), lattice.get("cols")
    sid_to_bmu = {s["sid"]: s["bmu"] for s in som_cache.get("sessions", [])}
    joined = [m for m in metrics if m.get("sid") in sid_to_bmu and m.get("day")]
    if not joined:
        return None
    joined = sorted(joined, key=lambda m: (m["day"], m["sid"]))

    waypoints = [{"day": m["day"], "cell": list(sid_to_bmu[m["sid"]])} for m in joined]
    trajectory = _downsample(waypoints, 24)
    # the smoothed drift (mood) the map draws: the raw per-session cells are the noise,
    # the drift is the signal. See _drift_path.
    drift = _drift_path([w["cell"] for w in waypoints],
                        [w["day"] for w in waypoints])

    anchor = now_day or max(m["day"] for m in joined)
    cutoff = (datetime.date.fromisoformat(anchor)
              - datetime.timedelta(days=field_window_days)).isoformat()
    in_window = [m for m in joined if m["day"] >= cutoff]
    by_cell = defaultdict(list)
    for m in in_window:
        r, c = sid_to_bmu[m["sid"]]
        by_cell[(r, c)].append(m)
    # "you are here" is where your recent WORK concentrates, NOT the last session and NOT
    # the most-sessions cell. Counting sessions equally over-weights quick solo blips: on
    # real data solo is ~half the sessions but under a fifth of the output tokens, while
    # orchestration is a few heavy sessions carrying most of the work. So weight the recent
    # window by output tokens (the work), ties to the more recent day. Fall back to the last
    # waypoint only when the window is empty.
    if by_cell:
        recency = {rc: max(m["day"] for m in ms) for rc, ms in by_cell.items()}
        work = {rc: sum(m.get("out_tok", 0) for m in ms) for rc, ms in by_cell.items()}
        current_cell = list(max(by_cell, key=lambda rc: (work[rc], recency[rc])))
    else:
        current_cell = trajectory[-1]["cell"]
    field = [[None] * cols for _ in range(rows)]
    support = [[0] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            cells = by_cell.get((r, c), [])
            support[r][c] = len(cells)
            if cells:
                v = vector(cells)["d_per_survkb"]
                field[r][c] = round(v, 4) if v is not None else None

    field_to_arm = {"orchestrator": "model", "worker": "worker", "effort": "effort"}
    gradient = {"arm_change": move, "target_cell": None, "vector": None, "grounded_in": 0}
    if move is not None:
        arm = field_to_arm.get(move.get("axis"))
        if arm:
            matched = [m for m in joined if m.get(arm) == move.get("to")]
            if matched:
                cells_rc = [sid_to_bmu[m["sid"]] for m in matched]
                mean_r = sum(rc[0] for rc in cells_rc) / len(cells_rc)
                mean_c = sum(rc[1] for rc in cells_rc) / len(cells_rc)
                target_cell = [round(mean_r), round(mean_c)]
                vect = [target_cell[0] - current_cell[0], target_cell[1] - current_cell[1]]
                gradient = {"arm_change": move, "target_cell": target_cell,
                            "vector": vect, "grounded_in": len(matched)}

    # per-cell meaning (for hover) and the per-session walk (for the time scrubber):
    # what each hex is (your dominant setup there) and how each session scored and where
    # it fell. This is what makes the map interactive and lets you replay the walk.
    rig_obj = _rig_objective_metrics(metrics, attribution, misery_block)
    by_cell_all = defaultdict(list)
    for m in joined:
        by_cell_all[tuple(sid_to_bmu[m["sid"]])].append(m)
    cell_meaning = []
    for (r, c), ms in sorted(by_cell_all.items()):
        dom_roles = modal([m.get("model_roles") for m in ms])
        obj = rig_obj.get(dom_roles, {})
        # flow is directly per-cell (misery is per session); efficiency and simplicity
        # come from the cell's dominant setup (they are git-attributed by rig).
        cell_flows = [100 - m["misery"] for m in ms if m.get("misery") is not None]
        # cargo: the durable work this cell actually moved (net surviving complexity over its
        # own sessions). This is the throughput axis efficiency is blind to: a lean cell can
        # win on eff (surviving per token) while carrying almost no load. The recommender uses
        # it so a bicycle is never advised over a truck. See _recommend_cells.
        cargo = sum(max(0, (m.get("born") or 0) - (m.get("killed") or 0)) for m in ms)
        # coordination (session-features@3): how much this cell's sessions had sibling workers
        # share files vs silo. Mean over the sessions that carry the signal; None when none do
        # (solo sessions, or data extracted before worker_files) so the map draws no core.
        coords = [m["coordination"] for m in ms if m.get("coordination") is not None]
        coord = round(sum(coords) / len(coords), 4) if coords else None
        cell_meaning.append({
            "cell": [r, c],
            "engine": modal([m.get("engine") for m in ms]),
            "model": modal([m.get("model") for m in ms]),
            "worker": modal([m.get("worker") for m in ms]),
            "effort": modal([m.get("effort") for m in ms]),
            "sessions": len(ms),
            "cargo": cargo,
            "coord": coord,
            "cost": field[r][c],
            "eff": obj.get("eff"),
            "flow": (round(sum(cell_flows) / len(cell_flows), 1) if cell_flows
                     else obj.get("flow")),
            "simp": obj.get("simp")})

    def _sess_cost(m):
        survc = m["born"] - m["killed"]
        survkb = survc / 1024 if survc > 0 else 0
        return round(m["dollars"] / survkb, 2) if survkb > 0 else None

    walk = [{"day": m["day"], "cell": list(sid_to_bmu[m["sid"]]),
             "flow": (round(100 - m["misery"], 1) if m.get("misery") is not None
                      else None),
             "cost": _sess_cost(m), "engine": m.get("engine"),
             "model": m.get("model"), "effort": m.get("effort"),
             "work": m.get("out_tok", 0)}  # weight prevalence by work, not session count
            for m in joined]

    return {"source": "learned",
            "lattice": {"rows": rows, "cols": cols},
            "sessions_mapped": len(joined),
            "trajectory": trajectory,
            "drift": drift,
            "current_cell": current_cell,
            "field_metric": "d_per_survkb",
            "field_lower_is_better": True,
            "field_window_days": field_window_days,
            "field": field,
            "support": support,
            "cell_meaning": cell_meaning,
            "walk": walk,
            "gradient": gradient}


def rig_space(metrics, attribution, misery_block, field_window_days=14, som_cache=None):
    """The operator's trajectory through the collapsed rig-space, plus the gradient
    at their current position toward the better region. Additive: None when there is
    not enough dated data; never touches the other meters."""
    dated = sorted((m for m in metrics if m.get("day")),
                   key=lambda m: (m["day"], m["sid"]))
    if len(dated) < 5:
        return None
    points = [_embed(m) for m in dated]
    mood, pers, path = _layered_trajectory(points)
    # a compact trajectory: (day, mood-position) waypoints, downsampled for the viz.
    waypoints = _downsample(
        [{"day": m["day"], "pos": p} for m, p in zip(dated, path)], 24)

    # the field + gradient: reuse the true-economy gradient ($/shipped-change over the
    # arms). Time-windowing the field to the recent horizon is a documented seam (the
    # git attribution is all-time; the SOM version windows the learned field).
    _ = field_window_days
    move = gradient_move(metrics, attribution, misery_block)
    gradient = None
    if move:
        # target position: the operator's dominant rig with the recommended arm-change
        # applied, embedded. The gradient is target - current (the PAD update vector).
        dom = {ax: modal([m.get(fld) for m in dated])
               for ax, fld in (("engine", "engine"), ("model", "model"),
                               ("worker", "worker"), ("effort", "effort"),
                               ("review_regime", "review_regime"))}
        field_to_arm = {"orchestrator": "model", "worker": "worker", "effort": "effort"}
        arm = field_to_arm.get(move["axis"])
        if arm:
            dom[arm] = move["to"]
        target = _embed(dom)
        cur = tuple(mood)
        gradient = {"arm_change": move, "target": target,
                    "vector": [round(target[k] - cur[k], 4) for k in range(len(cur))]}
    result = {"axes": list(RIG_AXES), "sessions": len(dated),
              "personality": list(pers), "mood": list(mood),
              "current": path[-1], "trajectory": waypoints, "gradient": gradient}
    # the learned map, additive over the hand-written trajectory above: only
    # attached when a SOM cache is present, so a no-cache run stays byte-identical.
    if som_cache:
        result["som"] = som_map(metrics, som_cache, move, field_window_days,
                                attribution=attribution, misery_block=misery_block)
    return result


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
                # honest unit: this whole prediction lives in the frontier's own
                # unit (surviving-KB per dollar), NOT the topline headline. The
                # frontier does not yet carry functionality-per-Mtok, so the lever
                # cannot predict the headline; the measure loop is ground truth on
                # that. Fields are named to make the unit unmistakable.
                "unit": "surviving-KB per dollar",
                "predicts": "engine-efficiency vector (depth), not the topline headline",
                "your_cell_efficiency": round(cell_eq, 4),
                "frontier_cell_efficiency": round(feq, 4),
                "predicted_efficiency": round(new_eq, 4),
                "predicted_efficiency_delta": round(new_eq - base_eq, 4)}
        if best is None or \
                cand["predicted_efficiency_delta"] > best["predicted_efficiency_delta"]:
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


def confounds(metrics, numerator, since, now, denom_empty=False):
    out = []
    out.append(f"Horizon: survival here is same-session (killed within the run), "
               f"and the git numerator is measured at HEAD over '{since}'. Not a "
               f"durable day/week horizon.")
    if denom_empty:
        out.append("Empty denominator: sessions carry a project but none named a "
                   "measured repo, so the topline output-token denominator is empty "
                   "and eq is null. Check --repos matches the sessions' projects.")
    n = len(metrics)
    if n < 30:
        out.append(f"Small N: only {n} code-sessions with survival in the window; "
                   f"per-cell numbers move on a few sessions.")
    # effort mix: the blended topline can move on an effort shift, not an engine change
    efforts = sorted({m["effort"] for m in metrics if m.get("effort")})
    if len(efforts) > 1:
        out.append(f"Effort mix: sessions span effort tiers {', '.join(efforts)}; "
                   f"the blended topline can move on an effort-mix shift rather than "
                   f"an engine change. Slice by_effort to hold it fixed.")
    # review-regime mix (a prime survival confound) or an uncontrolled regime
    regimes = sorted({m.get("review_regime", "unclassified") for m in metrics})
    real = [r for r in regimes if r != "unclassified"]
    if len(real) > 1:
        out.append(f"Review-regime mix: sessions span {', '.join(real)}; review "
                   f"regime moves horizon-survival, so it is a prime confound. Slice "
                   f"by_review_regime to hold it fixed before attributing a move.")
    elif not real:
        out.append("Review regime uncontrolled: no fingerprint labels, so the "
                   "review dimension is neither held fixed nor sliced. Run the "
                   "classifier (SKILL.md step 3b) to control for this confound.")
    # Selection / task-difficulty confound. Efficiency (surviving per output-Mtok) factors as
    # survival_rate x production_rate: surviving/born (how much of what you made stuck, which
    # falls on harder work) times born/Mtok (what you produced per token, the real thrift). If
    # the efficiency LEADER wins on survival_rate rather than production_rate, its edge is that
    # it was handed stickier, easier work, not that it is token-thrifty, and the raw ordering is
    # a difficulty artifact that would invert under a fixed task. Detect it and name it with the
    # operator's own numbers, so the report never sells "go leaner/cheaper" off a selection bias.
    by_eng = defaultdict(lambda: [0.0, 0.0, 0.0, 0])  # surviving, born, out_tok, n
    for m in metrics:
        born, killed, ot = m.get("born") or 0, m.get("killed") or 0, m.get("out_tok") or 0
        if ot <= 0 or born <= 0:
            continue
        g = by_eng[m.get("engine") or "?"]
        g[0] += max(0, born - killed); g[1] += born; g[2] += ot; g[3] += 1
    rows = [(e, surv / (ot / 1e6), surv / born, born / (ot / 1e6), k)
            for e, (surv, born, ot, k) in by_eng.items() if k >= 3 and ot > 0 and born > 0]
    if len(rows) >= 2:
        eff_leader = max(rows, key=lambda r: r[1])
        prod_leader = max(rows, key=lambda r: r[3])
        if eff_leader[0] != prod_leader[0] and eff_leader[3] > 0:
            out.append(
                f"Task difficulty uncontrolled (selection): efficiency = survival-rate x "
                f"production-rate, and the efficiency leader '{eff_leader[0]}' wins on "
                f"survival-rate ({eff_leader[2]:.0%}, stickier work), not token-thrift, it "
                f"produces {eff_leader[3]:,.0f} per Mtok while '{prod_leader[0]}' produces "
                f"{prod_leader[3]:,.0f} ({prod_leader[3] / eff_leader[3]:.1f}x) at "
                f"{prod_leader[2]:.0%} survival. So the raw efficiency ordering is "
                f"difficulty-mixed, not a thrift ranking; hold the task fixed with the "
                f"dynamometer (same task, different rigs) before reading it as one.")
    # non-overlapping fuel (session) and git (numerator) windows: the ratio would
    # divide functionality and fuel measured over different periods
    days = sorted(m["day"] for m in metrics if m.get("day"))
    start = survival_git._since_to_date(since, now)
    if days and start:
        now_date = datetime.datetime.fromtimestamp(
            now, datetime.timezone.utc).strftime("%Y-%m-%d")
        if days[-1] < start or days[0] > now_date:
            out.append(f"Window mismatch: fuel sessions span {days[0]}..{days[-1]} "
                       f"but the git numerator window is {start}..{now_date}; they "
                       f"do not overlap, so the topline divides functionality and "
                       f"fuel measured over different periods.")
    # bulk-import repos in the numerator
    for r in numerator["repos"]:
        if r.get("commits") and r["added"] and r["commits"] <= 2 and r["added"] > 20000:
            out.append(f"Terrain: repo '{r['name']}' added {r['added']:,} lines in "
                       f"{r['commits']} commit(s) at {r['pct']:.0f}% survival, likely a "
                       f"bulk import, not authored work; it inflates aggregate survival.")
    return out


def measure_vs_baseline(current_eq, baseline_path):
    """Close the loop: the actual TOPLINE move since a prior report (the ground
    truth on the headline). The prior lever's prediction is carried alongside but
    named for its own unit (survKB/$ engine-efficiency), a different quantity from
    the headline delta, so the two are never silently equated."""
    if not baseline_path or not os.path.exists(baseline_path):
        return None
    prev = json.load(open(baseline_path))
    prev_eq = (prev.get("topline") or {}).get("eq")
    predicted = (prev.get("lever") or {}).get("predicted_efficiency_delta")
    if prev_eq is None or current_eq is None:
        return None
    return {"metric": "topline (functionality per Mtok output)",
            "baseline_eq": prev_eq, "current_eq": current_eq,
            "actual_delta": round(current_eq - prev_eq, 4),
            "lever_predicted_efficiency_delta": predicted,
            "note": "actual_delta is the topline headline (ground truth); the "
                    "lever prediction is a surviving-KB-per-dollar move, a "
                    "different unit, not a headline forecast."}


def _proj_to_repo(proj, root):
    """Resolve a session's project string to a git repo path under `root`, or None.
    Handles Claude worktree projects (`<repo>--claude-worktrees-<name>` -> `<repo>`)
    and a dash/underscore fallback, so a worktree session still credits its repo."""
    base = proj.split("--claude-worktrees-")[0].strip()
    for name in (base, base.replace("-", "_"), base.replace("_", "-")):
        if not name:
            continue
        cand = os.path.join(root, name)
        if os.path.isdir(os.path.join(cand, ".git")):
            return cand
    return None


def discover_repos(snapshot_dir, root, since):
    """Fan out, do not guess: the repos to measure are the ones the operator's
    sessions actually worked in, discovered from the snapshot itself and pruned to
    those with commits in the window. Returns a sorted list of repo paths.

    A tool that measures only the repos it was handed will mislead whenever that hand
    is wrong. Discovery removes the hand."""
    sessions, _t, _c, _s = load_snapshot(snapshot_dir)
    repo_paths = set()
    for s in sessions.values():
        if s.get("proj"):
            repo = _proj_to_repo(s["proj"], root)
            if repo:
                repo_paths.add(repo)
    active = []
    for repo in sorted(repo_paths):
        # prune dead repos before the expensive blame: keep only those with commits
        # in the window.
        if survival_git.git(repo, "log", f"--since={since}", "--oneline", "-1").strip():
            active.append(repo)
    return active


def coverage_for(snapshot_dir, repos, root):
    """What fraction of the operator's sessions the measured repo set actually
    covers, and every project it does NOT, by session count. Surfaced in the report
    so a narrow repo set (the failure that made the tool measure 9% of a rig and say
    nothing) confesses itself instead of hiding."""
    sessions, _t, _c, _s = load_snapshot(snapshot_dir)
    measured_paths = {os.path.abspath(r) for r in repos}
    proj_sessions = defaultdict(int)
    for s in sessions.values():
        if s.get("proj"):
            proj_sessions[s["proj"]] += 1
    total, measured, unresolved = sum(proj_sessions.values()), 0, defaultdict(int)
    for proj, cnt in proj_sessions.items():
        repo = _proj_to_repo(proj, root)
        if repo and os.path.abspath(repo) in measured_paths:
            measured += cnt
        else:
            unresolved[proj.split("--claude-worktrees-")[0]] += cnt
    return {
        "root": root, "total_sessions": total, "measured_sessions": measured,
        "measured_pct": round(100 * measured / total, 1) if total else None,
        "measured_repos": sorted(os.path.basename(r) for r in repos),
        "unmeasured": sorted(({"proj": p, "sessions": c}
                              for p, c in unresolved.items()),
                             key=lambda x: -x["sessions"]),
    }


# vendored / generated / lockfile / minified paths: excluded from the numerator so
# imported bulk is not counted as the operator's authored, surviving logic.
_VENDORED_RE = re.compile(
    r"(^|/)(node_modules|vendor|third_party|third-party|dist|build|out|target|"
    r"\.venv|venv|site-packages|bower_components|external|deps|generated|__generated__|"
    r"testdata|fixtures|migrations)/|"
    r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|"
    r"go\.sum|composer\.lock|Gemfile\.lock)$|"
    r"\.(min\.js|min\.css|bundle\.js|map|lock)$|"
    r"(\.pb\.go|_pb2\.py|\.g\.dart|\.generated\.[a-z]+)$", re.I)

_BUCKETS = [(0, 1), (1, 3), (3, 7), (7, 14), (14, 30), (30, 90), (90, 10**6)]
_BUCKET_LABELS = ["<1d", "1-3d", "3-7d", "7-14d", "14-30d", "30-90d", ">90d"]


def _survival_agg(commits, surviving, complexity, since, now):
    """The survival aggregate (added / surviving / net_complexity / age buckets /
    fix share) from a single blame's per-commit data, same shape as
    survival_git.survival, so the numerator table is built without a second pass."""
    if not commits:
        return None
    agg = defaultdict(lambda: [0, 0])
    fix_added = 0
    for sha, c in commits.items():
        if c["added"] == 0:
            continue
        if survival_git.FIXY.search(c["subj"]):
            fix_added += c["added"]
        age_d = (now - c["ts"]) / 86400
        surv = surviving.get(sha, 0)
        for i, (lo, hi) in enumerate(_BUCKETS):
            if lo <= age_d < hi:
                agg[i][0] += c["added"]
                agg[i][1] += surv
                break
    total_added = sum(c["added"] for c in commits.values())
    total_surv = sum(surviving.get(s, 0) for s in commits)
    net_cx = sum(complexity.get(s, 0) for s in commits)
    return {"since": since, "commits": len(commits), "added": total_added,
            "surviving": total_surv, "net_complexity": net_cx,
            "pct": 100 * total_surv / max(1, total_added),
            "buckets": [(_BUCKET_LABELS[i], agg[i][0], agg[i][1])
                        for i in range(len(_BUCKET_LABELS))],
            "fix_added": fix_added, "fix_pct": 100 * fix_added / max(1, total_added)}


def _repo_git(repo, since, now, cache_dir):
    """ONE blame pass per repo, cached by (HEAD, since). Returns the whole git bundle
    the report needs from a repo: per-commit surviving lines and complexity (for the
    numerator, the durable-by-day maps, and the session attribution), the survival
    aggregate, and DORA changes. Re-running with an unchanged HEAD reads the cache and
    does no blame at all, so the every-run cost is near zero; only a repo whose HEAD
    moved is re-blamed. Blame is the expensive step and it happened three times per
    repo before this; now it happens once."""
    name = os.path.basename(os.path.normpath(repo))
    head = survival_git.git(repo, "rev-parse", "HEAD").strip()
    cpath = os.path.join(cache_dir, f"gitcache-{name}.json") if cache_dir else None
    key = f"{head}|{since}|v2-vendored-filter"  # bump to invalidate on numerator change
    if cpath and os.path.exists(cpath):
        try:
            cached = json.load(open(cpath))
            if cached.get("key") == key:
                commits = {sha: {**c, "paths": set(c["paths"])}
                           for sha, c in cached["commits"].items()}
                return {"name": name, "head": head, "blamed": False, "elapsed": 0.0,
                        "commits": commits, "surviving": cached["surviving"],
                        "complexity": cached["complexity"],
                        "survival": _survival_agg(commits, cached["surviving"],
                                                  cached["complexity"], since, now),
                        "changes": cached["changes"]}
        except Exception:
            pass
    t0 = time.time()
    commits = survival_git.window_commits(repo, since)
    surviving, complexity = {}, {}
    if commits:
        tracked = set(survival_git.git(repo, "ls-files").splitlines())
        paths = {p for c in commits.values() for p in c["paths"]} & tracked
        # exclude vendored / generated / lockfile / minified paths: the complexity
        # proxy counts decision points in ANY surviving line, so a single vendored
        # import (node_modules, vendor/, a lockfile, a *.min.js) can add thousands of
        # "decision points" that are not the operator's authored logic and would
        # dominate the numerator. Measure authored code, not imported bulk.
        paths = {p for p in paths if not _VENDORED_RE.search(p)}
        surviving, complexity = survival_git.surviving_by_commit(repo, paths)
    changes = survival_git.changes(repo, since, now=now)
    elapsed = time.time() - t0
    if cpath:
        try:
            json.dump({"key": key,
                       "commits": {sha: {**c, "paths": sorted(c["paths"])}
                                   for sha, c in commits.items()},
                       "surviving": surviving, "complexity": complexity,
                       "changes": changes}, open(cpath, "w"))
        except Exception:
            pass
    return {"name": name, "head": head, "blamed": True, "elapsed": elapsed,
            "commits": commits, "surviving": surviving, "complexity": complexity,
            "survival": _survival_agg(commits, surviving, complexity, since, now),
            "changes": changes}


def gather_git(repos, since, now, cache_dir, progress=True):
    """Blame every repo once, in parallel, with per-repo progress to stderr. Cached
    repos return instantly; only HEAD-moved repos are re-blamed. Returns {repo:
    bundle}. This is the fan-out, made cheap and transparent."""
    bundles, done, n = {}, 0, len(repos)
    if progress and n:
        print(f"measuring {n} repo(s) [cached repos are instant; only changed repos "
              f"re-blame]...", file=sys.stderr)
    workers = min(8, max(1, (os.cpu_count() or 2)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_repo_git, r, since, now, cache_dir): r for r in repos}
        for fut in concurrent.futures.as_completed(futs):
            repo = futs[fut]
            bundles[repo] = fut.result()
            done += 1
            if progress:
                b = bundles[repo]
                tag = f"blamed {b['elapsed']:.1f}s" if b["blamed"] else "cached"
                print(f"  [{done}/{n}] {b['name']}: {tag} "
                      f"({b['survival']['net_complexity'] if b['survival'] else 0} cx)",
                      file=sys.stderr)
    if progress and n:
        reblamed = sum(1 for b in bundles.values() if b["blamed"])
        secs = sum(b["elapsed"] for b in bundles.values())
        print(f"measured {n} repo(s): {reblamed} re-blamed ({secs:.0f}s), "
              f"{n - reblamed} from cache. Re-runs stay near-instant until a repo's "
              f"HEAD moves.", file=sys.stderr)
    return bundles


def shipped_by_day(bundles):
    """Durable shipped complexity / changes / fixes per calendar day, from the cached
    blame bundles. A non-fix commit is a DURABLE shipped change carrying the surviving
    complexity still blamed to it at HEAD; a fix/revert is remediation, not durable.
    Returns ({day: durable_changes}, {day: fixes}, {day: durable_complexity})."""
    shipped, fixes, complexity = defaultdict(int), defaultdict(int), defaultdict(int)
    for b in bundles.values():
        cx = b["complexity"]
        for sha, c in b["commits"].items():
            day = datetime.datetime.fromtimestamp(
                c["ts"], datetime.timezone.utc).strftime("%Y-%m-%d")
            if survival_git.FIXY.search(c["subj"]):
                fixes[day] += 1
                continue
            shipped[day] += 1
            complexity[day] += cx.get(sha, 0)
    return dict(shipped), dict(fixes), dict(complexity)


def attribute_work(bundles, since, snapshot_dir, tail=900.0):
    """Join surviving git work to the (model, effort) that authored it, from the
    cached blame bundles (no re-blame).

    Leverages horizon_attribute.load_sessions for the project+time match. A commit
    matches the session whose active window brackets its time (short tail tolerance);
    its surviving lines/complexity accrue to that session's ORCHESTRATOR (direct
    agent), EFFORT, and full model-ROLES config (orchestrator -> dominant worker).
    Survival is a property of the session, not of any one model inside it, so it is
    attributed to the RIG, never split below the session (there is no per-worker file
    record). Deterministic: commit times fixed at HEAD, session times fixed in the
    snapshot; a commit matching no session is counted, not dropped."""
    def _agg():
        return defaultdict(lambda: {"commits": 0, "surviving": 0, "net_complexity": 0})
    by_model, by_effort, by_roles = _agg(), _agg(), _agg()
    by_worker, by_engine = _agg(), _agg()
    matched = unmatched = 0
    for repo, b in bundles.items():
        sessions = horizon_attribute.load_sessions(snapshot_dir, b["name"])
        if not sessions:
            continue
        for s in sessions:  # precompute the rig config axes once per session
            s["_worker"] = (base_model(sorted(s["submix"],
                            key=lambda k: (-s["submix"][k], k))[0])
                            if s.get("submix") else "solo")
            s["_roles"] = f"{base_model(s.get('raw_model'))} -> {s['_worker']}"
        commits, surviving, complexity = b["commits"], b["surviving"], b["complexity"]
        if not commits:
            continue
        for sha, c in commits.items():
            if c["added"] == 0:
                continue
            cand = [s for s in sessions
                    if s["start"] - tail <= c["ts"] <= s["end"] + tail]
            if not cand:
                unmatched += 1
                continue
            s = min(cand, key=lambda s: abs((s["start"] + s["end"]) / 2 - c["ts"]))
            matched += 1
            eng = s.get("engine", "unknown")
            for agg, key in ((by_model, s["model"]), (by_effort, s["effort"]),
                             (by_roles, s["_roles"]), (by_worker, s["_worker"]),
                             (by_engine, eng)):
                a = agg[key]
                a["commits"] += 1
                a["surviving"] += surviving.get(sha, 0)
                a["net_complexity"] += complexity.get(sha, 0)
    return {
        "matched": matched, "unmatched": unmatched,
        "by_orchestrator": {k: by_model[k] for k in sorted(by_model)},
        "by_worker": {k: by_worker[k] for k in sorted(by_worker)},
        "by_engine": {k: by_engine[k] for k in sorted(by_engine)},
        "by_effort": {k: by_effort[k] for k in sorted(by_effort)},
        "by_model_roles": {k: by_roles[k] for k in sorted(by_roles)},
    }


def build_report(snapshot_dir, repos, since, frontier_path, harness, now,
                 baseline_path=None, granularity="week", labels_path=None,
                 coverage=None, dump_sessions_path=None):
    session_cost, usage_field = load_adapter_cost(harness)
    sessions, turns, code, survival = load_snapshot(snapshot_dir)
    misery = load_misery(snapshot_dir)  # {sid: {score, tags, evidence}}; {} if none
    som_cache = load_som(snapshot_dir)  # {} if absent; drives rig_space's learned map
    shared_map = load_shared_map(snapshot_dir)  # {} if absent; the federated commons map
    metrics = []
    for sid, s in sessions.items():
        m = session_metrics(s, turns, code, survival, session_cost, usage_field)
        if m:
            # the second meter: attach per-session misery (None if unscored), same
            # as survival is attached. It never enters EQ (operator-owned tradeoff).
            ms = misery.get(sid)
            m["misery"] = ms.get("score") if isinstance(ms, dict) else None
            metrics.append(m)
    metrics.sort(key=lambda m: m["sid"])  # deterministic order

    # SOM seam: dump the per-session metric list (the same grain the trajectory
    # and field join to) so session_features -> som_train can run out of band.
    # Additive; does not change the report. Deterministic (metrics already sorted).
    if dump_sessions_path:
        with open(dump_sessions_path, "w") as _f:
            _f.write(json.dumps(metrics, indent=2, sort_keys=True) + "\n")

    # every session's fingerprint (not just survival-having ones), for dating the
    # operator's real setup changes over ALL their runs, not the survival subset.
    all_fp = sorted(
        ({"day": s.get("day"), "engine": engine_of(s),
          "model": base_model(s.get("model")),
          "worker": worker_of(s), "model_roles": roles_of(s),
          "effort": modal([t.get("effort") for t in turns.get(sid, [])
                           if t.get("effort")])}
         for sid, s in sessions.items() if s.get("day")),
        key=lambda r: (r["day"], r["model"], r["engine"]))

    # pattern-dimension labels: explicit --labels, else alongside the snapshot.
    # Absent -> the three pattern dims stay pending; a no-cache run is unchanged.
    if labels_path is None:
        default = os.path.join(snapshot_dir, "fingerprint-labels.json")
        labels_path = default if os.path.exists(default) else None
    attach_labels(metrics, load_labels(labels_path))

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

    # resolve now first (the blame's age buckets and the confounds depend on it).
    now_val = now if now is not None else \
        datetime.datetime.now(datetime.timezone.utc).timestamp()
    # ONE cached, parallel blame pass per repo feeds the numerator, the durable-by-day
    # maps, and the session attribution. Re-runs with unchanged HEADs do no blame.
    bundles = gather_git(repos, since, now_val, cache_dir=snapshot_dir)

    # numerator per repo -- surviving KB (volume) and DORA changes (shipped units of
    # work) with change failure rate. Volume and throughput carry different signal.
    repo_rows = []
    tot_add = tot_surv = tot_ch = tot_fail = tot_cx = 0
    for repo in repos:
        b = bundles[repo]
        r, ch = b["survival"], b["changes"]
        row = {"name": b["name"], "changes": ch["changes"], "failed_changes": ch["failed"],
               "change_source": ch["source"],
               "change_failure_rate": ch["change_failure_rate"]}
        tot_ch += ch["changes"]
        tot_fail += ch["failed"]
        if r is None:
            row.update({"commits": 0, "added": 0, "surviving": 0, "pct": None,
                        "net_complexity": 0})
        else:
            row.update({"commits": r["commits"], "added": r["added"],
                        "surviving": r["surviving"], "pct": round(r["pct"], 2),
                        "net_complexity": r["net_complexity"]})
            tot_add += r["added"]
            tot_surv += r["surviving"]
            tot_cx += r["net_complexity"]
        repo_rows.append(row)
    numerator = {"repos": repo_rows, "total_added": tot_add,
                 "total_surviving": tot_surv,
                 "pct": round(100 * tot_surv / tot_add, 2) if tot_add else None,
                 "total_changes": tot_ch, "total_failed_changes": tot_fail,
                 "change_failure_rate": round(100 * tot_fail / tot_ch, 2)
                 if tot_ch else None,
                 "net_complexity": tot_cx,
                 "complexity_per_1k_lines": round(1000 * tot_cx / tot_surv, 1)
                 if tot_surv else None}
    # per-model / per-effort surviving work, via the git<->session join
    numerator["attribution"] = attribute_work(bundles, since, snapshot_dir)

    # topline denominator: scope output tokens to the sessions that worked the
    # measured repos (proj names a repo). Fall back to the whole window when no
    # session carries proj, so older snapshots still produce a (window-approx)
    # number rather than nothing.
    repo_names = [os.path.basename(os.path.normpath(r)) for r in repos]
    if any(m.get("proj") for m in metrics):
        denom_metrics = [m for m in metrics
                         if any(rn and rn in m["proj"] for rn in repo_names)]
    else:
        denom_metrics = metrics
    # sessions carry proj but none named a measured repo: the denominator is empty
    # and eq is null. Name it, so a null topline is explained, not silent.
    denom_empty = bool(metrics) and not denom_metrics

    # durable shipped complexity (the headline numerator): decision points that
    # landed in non-reverted commits and still survive at HEAD, per Mtok output.
    shipped_map, fixes_map, complexity_map = shipped_by_day(bundles)
    numerator["durable_complexity"] = sum(complexity_map.values())
    numerator["durable_changes"] = sum(shipped_map.values())

    frontier, fbytes = load_frontier(frontier_path)
    ss = same_shape(by_ee_cells, frontier)
    tl = topline(metrics, numerator, denom_metrics)
    lever = best_lever(by_ee_cells, frontier, tl["_survkb"], tl["_dollars"])
    tl = {k: v for k, v in tl.items() if not k.startswith("_")}  # drop internals
    measure = measure_vs_baseline(tl["eq"], baseline_path)
    # adaptive granularity: a month of data with daily changes should not be a
    # weekly rollup. Pick day for a short span, week for medium, month for long.
    if granularity == "auto":
        days = sorted(m["day"] for m in all_fp if m.get("day"))
        if days:
            d0 = datetime.date(*(int(x) for x in days[0].split("-")[:3]))
            d1 = datetime.date(*(int(x) for x in days[-1].split("-")[:3]))
            span = (d1 - d0).days
            granularity = "day" if span <= 70 else ("week" if span <= 550 else "month")
        else:
            granularity = "week"
    # The chart's per-day denominator is the day's output tokens (all survival-having
    # sessions), which is dense and smooth; the headline scopes its denominator to
    # measured-repo sessions, so its absolute value differs, but the chart's job is
    # the trend and the era ranking, and the durable-complexity numerator is what
    # separates the eras. (A per-day scoped denominator is too sparse: it divides by
    # near-zero on days the measured repos were quiet and spikes into the thousands.)
    tline = timeline(metrics, all_fp, granularity,
                     shipped=shipped_map, complexity=complexity_map)
    bs = babysitting(metrics)
    fuel = fuel_and_work(metrics, granularity)

    # the second meter: misery over the SAME fingerprint parameter space as
    # efficiency, sliced by every arm, never folded into EQ. None when unscored.
    scored = [m for m in metrics if m.get("misery") is not None]
    misery_block = None
    if scored:
        _overall = round(sum(m["misery"] for m in scored) / len(scored), 1)
        misery_block = {
            "overall": _overall,
            "flow": round(100 - _overall, 1),  # signed meter: how much you were in flow
            "n_scored": len(scored),
            "by_model": _misery_by(metrics, "model"),
            "by_worker": _misery_by(metrics, "worker"),
            "by_model_roles": _misery_by(metrics, "model_roles"),
            "by_effort": _misery_by(metrics, "effort"),
            "by_engine": _misery_by(metrics, "engine"),
            "by_routing": _misery_by(metrics, "routing"),
        }

    # navigation: gradient descent over the fingerprint on the true-economy objective
    # ($/surviving-work), from the operator's OWN runs. Never the frontier.
    rstats = rig_stats(metrics, numerator.get("attribution"), misery_block)
    navigation = gradient_move(metrics, numerator.get("attribution"), misery_block)
    rspace = rig_space(metrics, numerator.get("attribution"), misery_block,
                       som_cache=som_cache)

    # provenance
    repo_prov = []
    for repo in repos:
        head = survival_git.git(repo, "rev-parse", "HEAD").strip()
        repo_prov.append({"name": os.path.basename(os.path.normpath(repo)),
                          "head": head})
    report = {
        "provenance": {
            "harness": harness,
            "since": since,
            "snapshot": os.path.basename(os.path.normpath(snapshot_dir)),
            "sessions_with_survival": len(metrics),
            "repos": repo_prov,
            "repos_measured": len(repos),
            "frontier_sha256": hashlib.sha256(fbytes).hexdigest() if fbytes else None,
            "driver": "vibrant_report/1",
        },
        "governance": {
            "clean": True,
            "assert": "engine-craft only; no individual-vs-product, no person-vs-person",
            "constitution": "docs/governance.md",
        },
        "topline": tl,
        "misery": misery_block,
        "coverage": coverage,
        "fingerprint": fingerprint_summary(metrics, numerator),
        "babysitting": bs,
        "lever": lever,
        "navigation": navigation,
        "rig_stats": rstats,
        "rig_space": rspace,
        "shared_map": shared_map or None,
        "measure": measure,
        "timeline": tline,
        "fuel_and_work": {
            "granularity": granularity, "series": fuel,
            "by_model": fuel_sliced(metrics, granularity, "model"),
            "by_worker": fuel_sliced(metrics, granularity, "worker"),
            "by_model_roles": fuel_sliced(metrics, granularity, "model_roles"),
            "by_effort": fuel_sliced(metrics, granularity, "effort"),
            "by_engine": fuel_sliced(metrics, granularity, "engine"),
            "by_routing": fuel_sliced(metrics, granularity, "routing"),
            "by_review_regime": fuel_sliced(metrics, granularity, "review_regime"),
            "by_knowledge_practice": fuel_sliced(metrics, granularity,
                                                 "knowledge_practice"),
        },
        "vector_by_engine": vector_by_engine,
        "vector_by_engine_model": vector_by_engine_model,
        "numerator": numerator,
        "same_shape": ss,
        "claims": claim_verdicts(by_engine, metrics),
        "confounds": confounds(metrics, numerator, since, now_val,
                               denom_empty=denom_empty),
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
    bloat = tl.get("bloat")
    bl = f" Bloat {bloat:.0f} decision points per change (over-engineering; lower is leaner)." \
        if bloat is not None else ""
    L.append(f"# Your setup: {tl['eq']} durable shipped changes per Mtok output")
    L.append("")
    cfr = tl.get("change_failure_rate")
    cfr_s = f" Change failure rate {cfr}% (DORA)." if cfr is not None else ""
    L.append(f"Larger is better. Units of work (non-reverted commits) that landed and "
             f"still survive at HEAD, per million tokens the model generated, over "
             f"{tl['sessions']} sessions.{cfr_s} It counts what shipped, not its "
             f"complexity, so over-engineering cannot inflate it.{bl} Nothing leaves "
             f"your machine.")
    L.append("")
    mb = report.get("misery")
    if mb:
        # the second meter, beside the topline, never folded in. It is a function of
        # the whole fingerprint (topology usually matters more than the model), and
        # it is operator-relative: this is YOUR friction, comparable only across your
        # own rigs, never a verdict about a model.
        L.append(f"**Flow {mb.get('flow', round(100 - mb['overall'], 1))}/100.** How "
                 f"much you were in flow (100 minus friction from your own replies), "
                 f"larger is better. A second meter, never folded into efficiency.")
        L.append("")
    cov = report.get("coverage")
    if cov and cov.get("measured_pct") is not None and cov["measured_pct"] < 90:
        top = ", ".join(f"{u['proj']} ({u['sessions']})"
                        for u in cov.get("unmeasured", [])[:5])
        L.append(f"> Coverage: this measures {cov['measured_pct']}% of your sessions "
                 f"({cov['measured_sessions']}/{cov['total_sessions']}). Biggest "
                 f"unmeasured projects: {top}. Add them to --repos (or run with "
                 f"--repos auto) so the number reflects your whole rig, not a slice.")
        L.append("")
    if lever:
        verified = any(t in str(lever.get("proof") or "").lower()
                       for t in ("reproduced", "tier-2", "tier-3", "git-verif"))
        L.append("## Your biggest lever" if verified
                 else "## A lever to test (unverified)")
        L.append("")
        L.append(f"{lever['tweak']}")
        L.append("")
        if verified:
            L.append(f"A reproduced setup shaped like yours ({lever['engine']}, "
                     f"{lever['effort']} effort) retains "
                     f"{lever['frontier_cell_efficiency']} surviving-KB per dollar, "
                     f"against your {lever['your_cell_efficiency']}. Re-run with "
                     f"--baseline to confirm the move on your own data.")
        else:
            L.append(f"An unverified frontier claim (proof: {lever.get('proof')}) "
                     f"reports {lever['frontier_cell_efficiency']} surviving-KB per "
                     f"dollar for a setup shaped like yours ({lever['engine']}, "
                     f"{lever['effort']} effort), against your "
                     f"{lever['your_cell_efficiency']}. Reproduce it before trusting "
                     f"the number; a self-reported cell is a hypothesis, not a target.")
    else:
        L.append("You are at the frontier for every shape we can compare. Nothing "
                 "to suggest; contribute your result so the next person learns.")
    L.append("")
    if measure:
        L.append("## Since last time")
        L.append("")
        arrow = "up" if measure["actual_delta"] > 0 else \
                ("flat" if measure["actual_delta"] == 0 else "down")
        L.append(f"{measure['baseline_eq']} to {measure['current_eq']} "
                 f"(actual {measure['actual_delta']:+}, {arrow}).")
        L.append("")
    L.append("---")
    L.append("_This surface is one number. The parameters behind it -- fuel "
             "streams, babysitting, changes, complexity, and the timeline, sliced "
             "by model and effort -- live in report.html (charts) and report.json "
             "(data). Go there to descend._")
    L.append("")
    return "\n".join(L)


_CSS = """
.vibrant{color-scheme:light;
 --surface:#f4f3ef;--card:#ffffff;--ink:#141310;--ink2:#57544d;--muted:#8f8c83;
 --line:#e7e5dd;--grid:#e7e5dd;--axis:#cfcdc3;--accent:#2a78d6;--series:#2a78d6;
 --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;
 --c-cacheread:#2a78d6;--c-read:#eb6834;--c-output:#1baf7a;--c-work:#008300;
 --good:#008300;--up:#008300;--down:#e34948;--down-rgb:227,73,72;--shadow:20,19,16;
 --ink-rgb:28,25,23;--rust:#c2410c;--teal:#0f766e;--paper:#fdf8f4;
 font-family:system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
 color:var(--ink);background:var(--surface);max-width:760px;margin:0 auto;
 padding:28px 20px 40px;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])) .vibrant{
 color-scheme:dark;--surface:#141412;--card:#1c1b19;--ink:#f6f5f0;--ink2:#c7c5bb;
 --muted:#918e85;--line:#2e2d29;--grid:#2c2c2a;--axis:#3a3a36;--accent:#3987e5;
 --series:#3987e5;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;
 --c-cacheread:#3987e5;--c-read:#d95926;--c-output:#199e70;--c-work:#159015;
 --good:#199e70;--up:#199e70;--down:#e66767;--down-rgb:230,103,103;--shadow:0,0,0;
 --ink-rgb:237,234,230;--rust:#e2683a;--teal:#2dd4bf;--paper:#1c1b19;}}
:root[data-theme=dark] .vibrant{color-scheme:dark;--surface:#141412;--card:#1c1b19;
 --ink:#f6f5f0;--ink2:#c7c5bb;--muted:#918e85;--line:#2e2d29;--grid:#2c2c2a;
 --axis:#3a3a36;--accent:#3987e5;--series:#3987e5;--s1:#3987e5;--s2:#d95926;
 --s3:#199e70;--s4:#c98500;--s5:#d55181;--c-cacheread:#3987e5;--c-read:#d95926;
 --c-output:#199e70;--c-work:#159015;--good:#199e70;--up:#199e70;--down:#e66767;
 --down-rgb:230,103,103;--shadow:0,0,0;
 --ink-rgb:237,234,230;--rust:#e2683a;--teal:#2dd4bf;--paper:#1c1b19;}
.vibrant *{box-sizing:border-box;}
.vibrant .card{background:var(--card);border:1px solid var(--line);border-radius:18px;
 padding:30px 32px;box-shadow:0 1px 2px rgba(var(--shadow),.05),0 10px 34px rgba(var(--shadow),.07);
 position:relative;}
.vibrant .card .flow-ov{position:absolute;left:0;top:0;width:100%;height:100%;
 pointer-events:none;z-index:2;}
.vibrant .top{display:flex;justify-content:space-between;align-items:center;margin:0 0 26px;}
.vibrant .brand{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:800;
 letter-spacing:.16em;color:var(--ink);text-transform:uppercase;}
.vibrant .brand .mark{width:17px;height:15px;flex:none;display:block;}
.vibrant .brand .mark rect{fill:var(--accent);}
.vibrant .meta{font-size:12px;color:var(--muted);letter-spacing:.02em;font-variant-numeric:tabular-nums;}
.vibrant .meters{display:flex;gap:44px;flex-wrap:wrap;margin:6px 0 26px;}
.vibrant .meter{min-width:0;}
.vibrant .mv{font-size:72px;font-weight:730;letter-spacing:-.035em;line-height:.82;
 color:var(--accent);}
.vibrant .meter.mis .mv{color:var(--teal);}
.vibrant .meter.bloat .mv{color:var(--good);}
.vibrant .mn{font-size:15px;font-weight:700;color:var(--ink);margin-top:14px;
 letter-spacing:.01em;}
.vibrant .mu{font-size:11.5px;color:var(--muted);margin-top:2px;}
.vibrant .combined{margin:4px 0 18px;display:flex;justify-content:center;}
.vibrant .topgroup{position:relative;display:inline-flex;align-items:center;gap:74px;}
.vibrant .score-col{position:relative;z-index:1;text-align:left;}
.vibrant .cv{font-size:78px;font-weight:760;letter-spacing:-.04em;line-height:.82;
 color:var(--ink);font-variant-numeric:tabular-nums;display:inline-block;text-align:left;}
.vibrant .cn{font-size:14px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
 color:var(--muted);margin-top:12px;}
.vibrant .chint{font-size:11px;color:var(--muted);margin-top:3px;font-style:italic;
 max-width:26ch;line-height:1.35;}
.vibrant .cparts{position:relative;z-index:1;font-size:13px;color:var(--ink2);
 display:flex;flex-direction:column;gap:9px;align-items:flex-end;margin:0;}
.vibrant .merge-flow{position:absolute;left:0;top:0;width:100%;height:100%;
 pointer-events:none;z-index:0;overflow:visible;}
.vibrant .mtog{font:inherit;font-size:13px;color:var(--ink2);background:transparent;
 border:1.5px solid var(--line);border-radius:999px;padding:3px 12px;cursor:pointer;}
.vibrant .mtog b{color:var(--oc);font-variant-numeric:tabular-nums;}
.vibrant .mtog:hover{border-color:var(--oc);}
.vibrant .mtog[aria-pressed=true]{border-color:var(--oc);
 box-shadow:inset 0 0 0 1px var(--oc);}
.vibrant .mtog[aria-pressed=false]{opacity:.5;text-decoration:line-through;}
.vibrant .vb-detail{font-size:11px;color:var(--muted);margin-top:16px;min-height:16px;}
.vibrant .vb-detail b{color:var(--ink2);}
.vibrant .vb-rec{font-size:11px;color:var(--muted);margin-top:6px;min-height:14px;}
.vibrant .vb-rec b{color:var(--rust);}
.vibrant .vb-rec .rec-arrow{color:var(--teal);font-weight:800;margin-right:4px;}
.vibrant .vb-rec .rec-hold{color:var(--muted);}
.vibrant .mk-best{color:var(--rust);font-weight:700;}
.vibrant .mk-gen{color:var(--rust);font-weight:700;}
.vibrant .mk-day{color:var(--ink);font-weight:700;}
.vibrant .mk-mix{color:var(--muted);}
.vibrant .wave{margin:52px 0 24px;}
.vibrant .wave svg{width:100%;height:auto;}
.vibrant .wcap{font-size:10px;font-weight:700;letter-spacing:.11em;text-transform:uppercase;
 color:var(--muted);margin-bottom:6px;}
.vibrant .wlegend{display:flex;flex-wrap:wrap;gap:10px;margin-top:8px;font-size:12px;
 font-weight:700;align-items:center;}
.vibrant .wlegend .wl-note{color:var(--muted);font-weight:400;margin-left:auto;
 font-size:11px;}
.vibrant .wlegend .wl-key{display:inline-flex;gap:12px;align-items:center;color:var(--ink2);}
.vibrant .wlegend .wl-key span{display:inline-flex;align-items:center;gap:5px;}
.vibrant .wlegend .wl-key i{width:9px;height:9px;border-radius:2px;display:inline-block;}
.vibrant .obj-chip{font:inherit;font-weight:700;color:var(--oc);background:transparent;
 border:1.5px solid var(--line);border-radius:999px;padding:3px 11px;cursor:pointer;
 letter-spacing:.01em;}
.vibrant .obj-chip:hover{border-color:var(--oc);}
.vibrant .obj-chip[aria-pressed=true]{border-color:var(--oc);
 box-shadow:inset 0 0 0 1px var(--oc);}
.vibrant .wv-bar{cursor:crosshair;}
.vibrant #vb-summary{font-size:12.5px;color:var(--ink2);margin-top:10px;min-height:17px;}
.vibrant #vb-summary b{color:var(--rust);}
@media (max-width:560px){.vibrant .cv{font-size:56px;}}
.vibrant .row-h{font-size:10.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
 color:var(--muted);margin:0 0 10px;}
.vibrant .fp{margin:0 0 4px;}
.vibrant .arm{display:flex;align-items:center;gap:12px;margin:0 0 8px;}
.vibrant .arm-l{flex:none;width:52px;font-size:11px;font-weight:700;color:var(--ink2);
 text-transform:uppercase;letter-spacing:.05em;}
.vibrant .arm-v{flex:none;font-size:12px;color:var(--ink2);white-space:nowrap;min-width:96px;}
.vibrant .arm-v b{color:var(--ink);font-weight:650;}
.vibrant .arm-chip{font-size:12px;font-weight:600;color:var(--ink);
 background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:2px 9px;}
.vibrant .bar.mini{height:12px;border-radius:6px;overflow:hidden;flex:1;}
.vibrant .bar.mini .seg:first-child{border-radius:6px 0 0 6px;}
.vibrant .bar.mini .seg:last-child{border-radius:0 6px 6px 0;}
.vibrant .stack{margin:0;}
.vibrant .bar{display:flex;gap:2px;height:34px;}
.vibrant .seg{display:block;min-width:3px;}
.vibrant .seg:first-child{border-radius:8px 0 0 8px;}
.vibrant .seg:last-child{border-radius:0 8px 8px 0;}
.vibrant .seg:only-child{border-radius:8px;}
.vibrant .legend{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:10px;font-size:12.5px;color:var(--ink2);}
.vibrant .lg{display:inline-flex;align-items:center;gap:6px;}
.vibrant .lg i{width:9px;height:9px;border-radius:2px;display:inline-block;flex:none;}
.vibrant .lg b{color:var(--ink);font-weight:650;}
.vibrant .lever{background:var(--surface);border-radius:12px;padding:15px 17px;margin:0 0 24px;
 border-left:3px solid var(--accent);}
.vibrant .lever.ok{border-left-color:var(--good);}
.vibrant .lever.warn{border-left-color:var(--s4);}
.vibrant .cov{background:var(--surface);border-radius:12px;padding:14px 17px;
 margin:16px 0 0;border-left:3px solid var(--down);}
.vibrant .cov-h{font-size:13px;font-weight:700;color:var(--ink);margin:0 0 4px;}
.vibrant .cov-b{font-size:12.5px;color:var(--ink2);line-height:1.5;}
.vibrant .cov-b code{background:var(--card);border:1px solid var(--line);
 border-radius:5px;padding:1px 5px;font-size:11.5px;}
.vibrant .lever-h{font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
 color:var(--muted);margin:0 0 6px;}
.vibrant .lever-tweak{font-size:15px;font-weight:600;color:var(--ink);line-height:1.4;}
.vibrant .lever-more{margin-top:8px;}
.vibrant .lever-more summary{font-size:11.5px;font-weight:600;color:var(--accent);
 cursor:pointer;letter-spacing:.02em;list-style:none;}
.vibrant .lever-more summary::-webkit-details-marker{display:none;}
.vibrant .lever-more summary::before{content:"\\25B8 ";color:var(--muted);}
.vibrant .lever-more[open] summary::before{content:"\\25BE ";}
.vibrant .lever-prompt{margin:8px 0 4px;padding:10px 12px;background:var(--card);
 border:1px solid var(--line);border-radius:8px;font-size:12px;line-height:1.5;
 color:var(--ink2);white-space:pre-wrap;word-break:break-word;
 font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}
.vibrant .spark{width:224px;height:58px;display:block;}
.vibrant .trend-cap{font-size:12.5px;color:var(--ink2);}
.vibrant .trend-cap .up{color:var(--up);font-weight:650;}
.vibrant .trend-cap .down{color:var(--down);font-weight:650;}
.vibrant .measure{font-size:12.5px;color:var(--ink2);margin:12px 0 0;}
.vibrant .foot{margin-top:24px;padding-top:15px;border-top:1px solid var(--line);
 font-size:11px;letter-spacing:.03em;color:var(--muted);display:flex;justify-content:space-between;}
.vibrant h2{font-size:14px;font-weight:650;color:var(--ink);margin:34px 0 12px;letter-spacing:-.01em;}
.vibrant h2 .sub{font-weight:400;color:var(--muted);font-size:12px;letter-spacing:0;}
.vibrant h2 select{margin-left:8px;vertical-align:middle;}
.vibrant .fine{font-size:11px;color:var(--muted);margin-top:8px;}
.vibrant .breakdown{margin-top:28px;}
.vibrant .breakdown>summary{font-size:12px;font-weight:600;color:var(--accent);
 cursor:pointer;list-style:none;}
.vibrant .breakdown>summary::-webkit-details-marker{display:none;}
.vibrant .breakdown>summary::before{content:"\\25B8 ";color:var(--muted);}
.vibrant .breakdown[open]>summary::before{content:"\\25BE ";}
.vibrant p{font-size:13px;color:var(--ink2);margin:0 0 14px;line-height:1.5;}
.vibrant svg{max-width:100%;height:auto;}
.vibrant table{border-collapse:collapse;font-size:13px;margin-top:14px;width:100%;
 font-variant-numeric:tabular-nums;}
.vibrant th,.vibrant td{text-align:left;padding:6px 14px 6px 0;border-bottom:1px solid var(--line);color:var(--ink2);}
.vibrant th{color:var(--muted);font-weight:600;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;}
.vibrant td:first-child{color:var(--ink);}
.vibrant .flag{color:var(--accent);font-weight:650;}
.vibrant select{font:inherit;font-size:13px;padding:4px 9px;border:1px solid var(--line);
 border-radius:8px;background:var(--card);color:var(--ink);cursor:pointer;}
.vibrant ol{font-size:12.5px;color:var(--ink2);margin:6px 0;padding-left:20px;}
@media (max-width:560px){.vibrant{padding:14px 10px 28px;}.vibrant .card{padding:22px 20px;}
 .vibrant .mv{font-size:52px;}.vibrant .meters{gap:28px;}}
"""

_STACK_COLORS = ("var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)")


def _stack_bar(arm):
    """A segmented bar of a fingerprint arm's blend, categorical colors in fixed
    order with 2px surface gaps, and a dotted legend below (the stack at a glance)."""
    esc = _html.escape
    b = (arm or {}).get("blend") or []
    if not b:
        return ""
    segs, legend = [], []
    for i, s in enumerate(b[:5]):
        c = _STACK_COLORS[i % len(_STACK_COLORS)]
        segs.append(f'<span class="seg" style="flex:{s["sessions"]};background:{c}" '
                    f'title="{esc(str(s["value"]))} {s["share"]}%"></span>')
        legend.append(f'<span class="lg"><i style="background:{c}"></i>'
                      f'{esc(str(s["value"]))} <b>{s["share"]:.0f}%</b></span>')
    return (f'<div class="stack"><div class="bar">{"".join(segs)}</div>'
            f'<div class="legend">{"".join(legend)}</div></div>')


def _arm_row(label, arm):
    """One fingerprint axis as a compact row: a one-word axis label, then either a
    blend bar with the dominant value (countable dims) or a single classified label
    (pattern dims). Six of these ARE the N-dim rig fingerprint on the card, not one
    collapsed categorical."""
    esc = _html.escape
    if isinstance(arm, str):  # a pattern dimension: one classified label
        val = arm.split(" (")[0]
        if "pending" in val or not val:
            return ""
        return (f'<div class="arm"><span class="arm-l">{esc(label)}</span>'
                f'<span class="arm-chip">{esc(val)}</span></div>')
    b = (arm or {}).get("blend") or []
    if not b:
        return ""
    segs = "".join(
        f'<span class="seg" style="flex:{s["sessions"]};'
        f'background:{_STACK_COLORS[i % len(_STACK_COLORS)]}" '
        f'title="{esc(str(s["value"]))} {s["share"]}%"></span>'
        for i, s in enumerate(b[:5]))
    dom = b[0]
    return (f'<div class="arm"><span class="arm-l">{esc(label)}</span>'
            f'<span class="bar mini">{segs}</span>'
            f'<span class="arm-v"><b>{esc(str(dom["value"]))}</b> {dom["share"]:.0f}%'
            f'</span></div>')


def _sparkline(eqs, W=224, H=58):
    """Compact trend sparkline: accent line, faint area, a dot on the latest week."""
    if len(eqs) < 2:
        return ""
    pad = 4
    lo, hi = min(eqs), max(eqs)
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    n = len(eqs)

    def X(i):
        return pad + (W - 2 * pad) * i / (n - 1)

    def Y(v):
        return pad + (H - 2 * pad) * (1 - (v - lo) / (hi - lo))

    line = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(eqs))
    area = f"{X(0):.1f},{H - pad:.1f} {line} {X(n - 1):.1f},{H - pad:.1f}"
    return (f'<svg class="spark" viewBox="0 0 {W} {H}" role="img" aria-label="trend">'
            f'<polygon points="{area}" fill="var(--accent)" opacity="0.10"/>'
            f'<polyline points="{line}" fill="none" stroke="var(--accent)" '
            f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{X(n - 1):.1f}" cy="{Y(eqs[-1]):.1f}" r="3.4" '
            f'fill="var(--accent)"/></svg>')


def _som_field_opacity(v, lo, hi, lower_better):
    """Normalize a field value to a fill opacity: single-hue ramp, monotonic in
    lightness. Low opacity blends toward the card background (cheap reads light
    and calm), high opacity is the saturated cost hue (costly reads dark and
    hot). Never encodes meaning by hue alone."""
    # log scale: d_per_survkb is a ratio with a long tail, so linear normalization
    # squashes the whole cheap-to-mid range against one expensive outlier and the
    # map loses its midrange contrast. Log spreads it so cells actually differ.
    if hi <= lo or v <= 0 or lo <= 0:
        t = 0.5
    else:
        t = (math.log(v) - math.log(lo)) / (math.log(hi) - math.log(lo))
        if not lower_better:
            t = 1 - t
    t = min(max(t, 0.0), 1.0)
    return 0.10 + 0.80 * t


def _rank_opacity(v, sorted_vals, lower_better=True):
    """A dynamic, range-sensitive shade: opacity by the value's RANK among the cells
    actually present, not by its position on a fixed lo..hi ramp. Histogram
    equalization, in effect. A fixed (even log) ramp smooths a clumped distribution
    into near-uniform grey, the exact washout that made the maps unreadable; ranking
    spreads whatever cells exist across the full ink range, so differences always
    show and more data yields more distinguishable shades. Ties share a shade (mid
    rank). lower_better keeps the cost convention (dark = costlier)."""
    n = len(sorted_vals)
    if n <= 1:
        return 0.5
    less = sum(1 for x in sorted_vals if x < v)
    eq = sum(1 for x in sorted_vals if x == v)
    t = (less + eq / 2.0) / n  # mid-rank percentile in (0, 1)
    if not lower_better:
        t = 1.0 - t
    return 0.10 + 0.80 * min(max(t, 0.0), 1.0)


# SOM map skins. The 3dl brand mark IS a Self-Organizing Map (3dl.dev/brand): ink
# cells, one rust peak unit, teal for links, on paper. So the maps ARE the logo, drawn
# from the operator's data. "classic" keeps the earlier red cost hue; "ink" and
# "ink-hex" render the 3dl mark (ink-shaded cells, the current cell as the rust peak,
# a teal move-arrow), rectangular or hexagonal.

_SOM_STYLES = {
    "classic": {"cell": "var(--down-rgb)", "trail": "var(--accent)",
                "arrow": "var(--good)", "cur_stroke": "var(--ink)",
                "cur_fill": "var(--card)", "cur_dot": "var(--ink)",
                "hex": False, "empty_dash": True},
    "ink": {"cell": "var(--ink-rgb)", "trail": "var(--ink)", "arrow": "var(--teal)",
            "cur_stroke": "var(--rust)", "cur_fill": "var(--paper)",
            "cur_dot": "var(--rust)", "hex": False, "empty_dash": False},
    "ink-hex": {"cell": "var(--ink-rgb)", "trail": "var(--ink)", "arrow": "var(--teal)",
                "cur_stroke": "var(--rust)", "cur_fill": "var(--paper)",
                "cur_dot": "var(--rust)", "hex": True, "empty_dash": False},
}


def _lens_label(x, y, fs, col, txt):
    """A haloed, bold region label for a map lens: reads over cells and tints alike."""
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" font-size="{fs}" '
            f'font-weight="700" letter-spacing="0.06em" paint-order="stroke" '
            f'stroke="var(--card)" stroke-width="3" stroke-linejoin="round" '
            f'fill="{col}">{txt}</text>')


def _rig_short(c):
    """A cell's rig in the shared taxonomy vocabulary, compact enough for a map label:
    orchestrator model (with worker when it delegates) then the engine."""
    eng = c.get("engine") or "?"
    model = c.get("model") or "?"
    worker = c.get("worker")
    core = f"{model}›{worker}" if (worker and worker != "solo") else model
    return f"{core} · {eng}"


def _hex_pts(cx, cy, rr):
    """Flat point string for a hexagon centred at (cx, cy) with circumradius rr."""
    return " ".join(f"{cx + rr * math.cos(math.radians(a)):.1f},"
                    f"{cy - rr * math.sin(math.radians(a)):.1f}"
                    for a in (90, 150, 210, 270, 330, 30))


def _mark_hex(cx, cy, rr, col, tag, rig, W, H):
    """One clean, high-contrast cell mark: a light fill and a bold ring on the hex, and a
    two-line label (TAG over rig) anchored above the hex when there is room, else below,
    always clamped inside the frame. No blur, no tint field. This is the whole vocabulary of
    the map's marks."""
    pts = _hex_pts(cx, cy, rr)
    fs = 11
    halfw = max(3, len(rig)) * fs * 0.30 + 5
    lx = min(max(cx, halfw + 3), W - halfw - 3)
    if (cy - rr - 30) > 2:                 # room above: rig near the hex, tag over it
        rig_y = cy - rr - 8
        tag_y = rig_y - (fs + 3)
    else:                                  # near the top edge: drop the label below
        tag_y = min(cy + rr + 16, H - fs - 5)
        rig_y = tag_y + fs + 3
    lab = (f'<text x="{lx:.1f}" y="{tag_y:.1f}" text-anchor="middle" font-size="{fs + 1}" '
           f'font-weight="800" letter-spacing="0.1em" paint-order="stroke" '
           f'stroke="var(--card)" stroke-width="3.5" stroke-linejoin="round" '
           f'fill="{col}">{_html.escape(tag)}</text>'
           + _lens_label(lx, rig_y, fs, col, _html.escape(rig)))
    return (f'<polygon points="{pts}" fill="{col}" opacity="0.18"/>'
            f'<polygon points="{pts}" fill="none" stroke="{col}" stroke-width="3.4"/>{lab}')


def _rig_zones(cmeta, ctr, hstep, cell, W, H, current_cell, bestfn):
    """Mark where YOU work, and nothing else. One bold clay hex on your current cell with
    its rig named above. No tint washes (blur behind data reads as a smudge, not a region)
    and no secondary optima (they only crowd the map). BEST is drawn client-side, reactive
    to the score arms. Returns ("", ontop): a single clean mark in the top layer."""
    if not current_cell:
        return "", ""
    you = next((i for i in range(len(cmeta))
                if list(cmeta[i]["cell"]) == list(current_cell)), None)
    if you is None:
        return "", ""
    cx, cy = ctr(*cmeta[you]["cell"])
    return "", _mark_hex(cx, cy, cell * 0.56, "#B0553A", "YOU",
                         _rig_short(cmeta[you]), W, H)


# Civ-V territory colours: (soft terrain fill, bright national-border). Mid-tones that read
# on dark and light alike; not a capability ranking, just distinct identities.
_CIV_TERR = {"solo": ("#3F6E8E", "#6FA0C6"), "delegate": ("#8A6D4B", "#C9A06A"),
             "workflow": ("#6E5A8A", "#A98BD0")}
_CIV_YOU = "#C56A4C"
# the coordination "core": a bright inner hex sized by how much a rig's sibling workers
# share files (session-features@3 coordination axis). Solo cells have no core (a single
# actor cannot coordinate). Neutral by construction: bright is not "better", survival judges.
_CIV_COORD = "#6FD6C9"


def _civ_nbrs(r, c):
    """Pointy-top odd-r hex neighbours, in the vertex/edge order [NW, W, SW, SE, E, NE], so a
    border edge can be matched to the cell across it."""
    d = ([(-1, 0), (0, -1), (1, 0), (1, 1), (0, 1), (-1, 1)] if r % 2
         else [(-1, -1), (0, -1), (1, -1), (1, 0), (0, 1), (-1, 0)])
    return [(r + dr, c + dc) for dr, dc in d]


def render_civ_map(som_block, svg_id=None, compact=True):
    """The rig fingerprint as a Civ-V map: engine TERRITORIES traced with national-style
    borders (self-evident like a strategy map) over the soft glow (atmospheric), cost-shaded
    hexes underneath, YOU fixed as your capital, and BEST plus the move drawn client-side so
    they react to the enabled score arms. One landscape map: identity and next-move in a
    single picture, no second panel. The geometry is emitted as data-* so the JS can place
    the reactive BEST on any cell."""
    lat = som_block.get("lattice") or {}
    rows, cols = lat.get("rows"), lat.get("cols")
    cmeta = som_block.get("cell_meaning") or []
    if not (rows and cols and cmeta):
        return ""
    cm = {tuple(c["cell"]): c for c in cmeta}
    eng = {tuple(c["cell"]): c.get("engine") for c in cmeta if c.get("engine")}
    cur = som_block.get("current_cell")
    esc = _html.escape
    cell = 26 if compact else 34
    hstep, vstep, pad, rr = cell + 2, (cell + 2) * 0.87, 8, cell * 0.575

    def ctr(r, c):
        return (pad + cell / 2 + c * hstep + (hstep / 2 if r % 2 else 0),
                pad + cell / 2 + r * vstep)

    def verts(cx, cy):
        return [(cx + rr * math.cos(math.radians(a)), cy - rr * math.sin(math.radians(a)))
                for a in (90, 150, 210, 270, 330, 30)]

    def poly(cx, cy):
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in verts(cx, cy))

    def poly_in(cx, cy, rf):
        return " ".join(f"{cx + (x - cx) * rf:.1f},{cy + (y - cy) * rf:.1f}"
                        for x, y in verts(cx, cy))
    W = pad * 2 + cell / 2 + (cols - 1) * hstep + hstep / 2 + cell / 2
    H = pad * 2 + cell / 2 + (rows - 1) * vstep + cell / 2

    glow, fills, cells, cores, borders, zg = [], [], [], [], [], {}
    for (r, c), e in eng.items():
        cx, cy = ctr(r, c)
        V = verts(cx, cy)
        col, bcol = _CIV_TERR.get(e, ("#6E6E76", "#9A9AA2"))
        glow.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{cell * 0.9:.1f}" fill="{col}" '
                    f'opacity="0.16" filter="url(#cvg)"/>')
        fills.append(f'<polygon points="{poly(cx, cy)}" fill="{col}" opacity="0.28"/>')
        cost = cm[(r, c)].get("cost")
        cop = 0.0 if cost is None else min(0.55, 0.10 + 0.45 * min(cost / 6.0, 1.0))
        # the cost hex is the HOVER target for this cell (data-r/data-c so the JS can decode
        # exactly which rig it is); the glow, borders, labels and marks are pointer-transparent.
        cells.append(f'<polygon class="civ-cell" data-r="{r}" data-c="{c}" '
                     f'points="{poly(cx, cy)}" fill="rgba(18,18,20,{cop:.2f})" '
                     f'stroke="rgba(160,160,170,0.10)" stroke-width="1"/>')
        # coordination core: an inner hex sized (and brightened) by the cell's coordination.
        # None/absent (older data) or ~0 (siloed / solo) draws nothing.
        co = cm[(r, c)].get("coord")
        if isinstance(co, (int, float)) and co > 0.02:
            co = min(1.0, co)
            cores.append(f'<polygon points="{poly_in(cx, cy, 0.20 + 0.55 * co)}" '
                         f'fill="{_CIV_COORD}" opacity="{0.5 + 0.35 * co:.2f}"/>')
        for i, nb in enumerate(_civ_nbrs(r, c)):
            if eng.get(nb) != e:  # this edge is on the territory boundary: draw a border
                a, b = V[i], V[(i + 1) % 6]
                borders.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" '
                               f'y2="{b[1]:.1f}" stroke="{bcol}" stroke-width="2.4" '
                               f'stroke-linecap="round"/>')
        z = zg.setdefault(e, [0.0, 0.0, 0])
        z[0] += cx
        z[1] += cy
        z[2] += 1
    labels = []
    for e, (sx, sy, n) in zg.items():
        bcol = _CIV_TERR.get(e, ("", "#9A9AA2"))[1]
        labels.append(f'<text x="{sx / n:.1f}" y="{sy / n:.1f}" text-anchor="middle" '
                      f'font-size="12" font-weight="800" letter-spacing="0.14em" opacity="0.4" '
                      f'paint-order="stroke" stroke="var(--card)" stroke-width="3" '
                      f'fill="{bcol}">{esc(e.upper())}</text>')
    idattr = f' id="{svg_id}"' if svg_id else ''
    geo = (f' data-cell="{cell}" data-hstep="{hstep}" data-vstep="{vstep:.3f}" '
           f'data-pad="{pad}" data-rr="{rr:.2f}"')
    defs = ('<defs><filter id="cvg" x="-60%" y="-60%" width="220%" height="220%">'
            '<feGaussianBlur stdDeviation="9"/></filter></defs>')
    # YOU and BEST are NOT baked here: the JS draws them into .zciv for whatever timeline
    # slice is selected, so they vary with the data considered (see renderCivMarks).
    return (f'<svg{idattr}{geo} viewBox="0 0 {W:.0f} {H:.0f}" role="img" '
            f'style="width:100%;height:auto;display:block" aria-label="rig fingerprint as a '
            f'map: engine territories with borders; YOU and the best rig marked by the '
            f'current timeline selection">{defs}'
            f'<g pointer-events="none">{"".join(glow)}{"".join(fills)}</g>'
            f'{"".join(cells)}'
            f'<g pointer-events="none">{"".join(cores)}{"".join(borders)}{"".join(labels)}</g>'
            f'<g class="zciv" pointer-events="none"></g></svg>')


def render_som_map(som_block, title="Where you work",
                   subtitle="each hexagon is a way you work, shaded by what it costs",
                   legend_bits=None, style="classic", compact=False, svg_id=None,
                   js_arrow=False):
    """The learned SOM lattice (item 4): a rows x cols grid shaded by cost per
    cell, the trajectory that walked it, the current cell, and the arrow to a
    cheaper cell already sometimes used. Pure function of rig_space['som'];
    matches the sparkline / efficiency-over-time SVG idiom (viewBox, role=img,
    aria-label, the report's own CSS vars), no external assets. Jitter on the
    trajectory is a deterministic function of index, never random, so the
    render is byte-identical for the same input. title/subtitle/legend_bits let
    the shared-frontier map (item C) reuse the same drawing with its own words."""
    if not som_block:
        return ""
    esc = _html.escape
    lattice = som_block.get("lattice") or {}
    rows, cols = lattice.get("rows") or 0, lattice.get("cols") or 0
    if rows <= 0 or cols <= 0:
        return ""
    field = som_block.get("field") or []
    support = som_block.get("support") or []
    lower_better = som_block.get("field_lower_is_better", True)
    metric = som_block.get("field_metric", "d_per_survkb")

    def fval(r, c):
        try:
            return field[r][c]
        except (IndexError, TypeError):
            return None

    def sval(r, c):
        try:
            v = support[r][c]
            return v if v is not None else 0
        except (IndexError, TypeError):
            return 0

    have = [v for v in (fval(r, c) for r in range(rows) for c in range(cols))
            if v is not None]
    lo, hi = (min(have), max(have)) if have else (0.0, 0.0)
    ranked = sorted(have)  # for the dynamic, range-sensitive cost shade (see _rank_opacity)
    smax = max([sval(r, c) for r in range(rows) for c in range(cols)] + [0]) or 1

    pal = _SOM_STYLES.get(style, _SOM_STYLES["classic"])
    hexed = pal["hex"]
    cell, gap = (28, 2) if compact else (42, 3)
    pad_l, pad_t, pad_r, pad_b = (3, 3, 3, 3) if compact else (14, 24, 14, 14)
    if hexed:
        hstep, vstep = cell + gap, (cell + gap) * 0.87
        gw = cols * hstep + hstep / 2
        gh = (rows - 1) * vstep + cell
    else:
        hstep = vstep = cell + gap
        gw = cols * cell + (cols - 1) * gap
        gh = rows * cell + (rows - 1) * gap
    W, H = pad_l + gw + pad_r, pad_t + gh + pad_b

    def center(r, c):
        if hexed:
            return (pad_l + cell / 2 + c * hstep + (hstep / 2 if r % 2 else 0),
                    pad_t + cell / 2 + r * vstep)
        return (pad_l + c * hstep + cell / 2, pad_t + r * vstep + cell / 2)

    def hexpts(cx, cy, rf=0.56):
        rr = cell * rf
        return " ".join(f"{cx + rr * math.cos(math.radians(a)):.1f},"
                        f"{cy - rr * math.sin(math.radians(a)):.1f}"
                        for a in (90, 150, 210, 270, 330, 30))

    def marker(cx, cy, cls, stroke, sw, extra=""):
        # a marker that matches the cell shape: a hex outline (or rect), not a circle.
        if hexed:
            return (f'<polygon class="{cls}" points="{hexpts(cx, cy)}" fill="none" '
                    f'stroke="{stroke}" stroke-width="{sw}"{extra}/>')
        return (f'<rect class="{cls}" x="{cx - cell / 2:.1f}" y="{cy - cell / 2:.1f}" '
                f'width="{cell}" height="{cell}" rx="4" fill="none" stroke="{stroke}" '
                f'stroke-width="{sw}"{extra}/>')

    def cell_shape(cx, cy, attrs, title=""):
        inner = f'<title>{title}</title>' if title else ''
        if hexed:
            return (f'<polygon class="som-cell" points="{hexpts(cx, cy)}" '
                    f'{attrs}>{inner}</polygon>')
        return (f'<rect class="som-cell" x="{cx - cell / 2:.1f}" y="{cy - cell / 2:.1f}" '
                f'width="{cell}" height="{cell}" rx="4" {attrs}>{inner}</rect>')

    # Civ-V-style LENSES on the clean map. Each cell is a specific RIG (a permutation in the
    # taxonomy: engine x model x worker x effort); the SOM lays similar rigs next to each
    # other. The default lens partitions the map into rig ZONES -- basins around the notable
    # rigs (YOU, the global BEST, other regional optima), each NAMED in the taxonomy so a
    # viewer locates themselves and the target in one vocabulary. Other lenses read a single
    # axis (efficiency heat, engine territory). One shows at a time; the grid is untouched:
    # tints ride behind the cells, labels on top.
    zdefs, lens_tints, lens_labels, you_mark = "", "", "", ""
    cmeta = som_block.get("cell_meaning") if hexed else None
    if cmeta:
        def _pct(vals):
            # percentile rank of each value in [0,1]; handles long tails without a scale.
            order = sorted(range(len(vals)), key=lambda i: vals[i])
            n = len(vals)
            pr = [0.0] * n
            for rank, i in enumerate(order):
                pr[i] = rank / (n - 1) if n > 1 else 1.0
            return pr
        # precompute per-metric percentiles across occupied cells (long-tailed, so rank).
        idx = list(range(len(cmeta)))
        pct = {}
        for key in ("eff", "simp", "flow"):
            have = [(i, cmeta[i].get(key)) for i in idx if cmeta[i].get(key) is not None]
            if have:
                pr = _pct([v for _, v in have])
                pct[key] = {i: p for (i, _), p in zip(have, pr)}

        def _best(i):
            # the "best region": mean of whatever quality percentiles this cell has.
            ps = [pct[k][i] for k in ("eff", "simp", "flow") if i in pct.get(k, {})]
            return sum(ps) / len(ps) if ps else None

        def _engine(c):
            return c.get("engine")
        # LENSES colour the AREAS of the map with a FLAT per-cell hex fill: crisp territories,
        # never a blur (blur behind data reads as a smudge). `engine` = solo / delegate /
        # workflow territories, named at their centroids (default); `efficiency` = a green
        # quality heat. The lens toggle swaps the area colouring; YOU (where your work is) and
        # BEST (the top rig for the enabled score arms) are drawn ALWAYS, over any lens.
        lenses = [
            {"name": "engine", "kind": "cat", "key": _engine,
             "hue": {"solo": "#4E6E8E", "delegate": "#8A6D4B", "workflow": "#7C5E8B"}},
            {"name": "efficiency", "kind": "heat",
             "val": (lambda i: pct.get("eff", {}).get(i)), "hue": "#3F7D5A", "peak": "PEAK"},
        ]
        cur_cell = som_block.get("current_cell")
        fs = 10 if compact else 12
        gap = fs * 1.55  # min vertical gap between two labels that overlap in x
        crad = cell * 0.88  # soft radius: adjacent same-hue glows merge into one region
        tint_groups, lab_groups, any_drawn = [], [], False
        for li, L in enumerate(lenses):
            name, kind, hue = L["name"], L["kind"], L["hue"]
            tints, labs = [], []
            if kind == "cat":
                # a SOFT glow per cell coloured by its category: adjacent same-category cells
                # merge into one glowing region (types read as territories, not hard tiles;
                # glows atmospherically on dark, stays gentle on light). The territories are
                # NAMED in the legend below the maps, so nothing competes with YOU / BEST.
                for cmi in cmeta:
                    k = L["key"](cmi)
                    if not k:
                        continue
                    cx, cy = center(*cmi["cell"])
                    any_drawn = True
                    tints.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{crad:.1f}" '
                                 f'fill="{hue.get(k, "var(--muted)")}" opacity="0.26" '
                                 f'filter="url(#zblur)"/>')
            else:  # heat
                cells = []
                for i in idx:
                    v = L["val"](i)
                    if v is None:
                        continue
                    cx, cy = center(*cmeta[i]["cell"])
                    cells.append((cx, cy, v))
                if len(cells) >= 3:
                    pr = _pct([v for _, _, v in cells])
                    for (cx, cy, _v), p in zip(cells, pr):
                        any_drawn = True
                        op = 0.05 + 0.40 * (p ** 1.3)  # gamma: top cells glow, low fade out
                        tints.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{crad:.1f}" '
                                     f'fill="{hue}" opacity="{op:.3f}" filter="url(#zblur)"/>')
                    # no PEAK label: the darkest-green cell already reads as the peak, and a
                    # pin would collide with the always-on BEST mark (BEST == the eff peak when
                    # efficiency is the target).
            disp = "" if li == 0 else ' style="display:none"'
            tint_groups.append(f'<g class="som-lens-t" data-lens="{name}"{disp}>'
                               f'{"".join(tints)}</g>')
            lab_groups.append(f'<g class="som-lens-l" data-lens="{name}"{disp}>'
                              f'{"".join(labs)}</g>')
        if any_drawn:
            zdefs = (f'<defs><filter id="zblur" x="-40%" y="-40%" width="180%" '
                     f'height="180%"><feGaussianBlur stdDeviation="{cell * 0.40:.1f}"/>'
                     f'</filter></defs>')
            lens_tints, lens_labels = "".join(tint_groups), "".join(lab_groups)
        # YOU: an always-on clay mark on your current cell, drawn over whatever lens is active.
        _, you_mark = _rig_zones(cmeta, center, hstep, cell, W, H, cur_cell, _best)

    idattr = f' id="{svg_id}"' if svg_id else ''
    # shape the grid as an oval by TAPERING columns per row: middle rows full width,
    # the top and bottom rows narrower, so the outline is a rounded oval built from
    # whole hexagons (no clipped corners). Cells outside the taper still exist for
    # hover and the scrubber, but draw transparent so only the oval is visible.
    rc0 = (rows - 1) / 2.0

    def _row_span(r):
        if not hexed or rows < 3:
            return 0, cols
        frac = math.sqrt(max(0.0, 1.0 - ((r - rc0) / (rc0 + 0.6)) ** 2))
        ncol = max(1, round(cols * frac))
        start = (cols - ncol) // 2
        return start, start + ncol
    parts = [f'<svg{idattr} viewBox="0 0 {W:.0f} {H:.0f}" role="img" aria-label="learned '
             f'working-style map: hexagons in soft engine territories, with YOU and the '
             f'target-best rig marked">', zdefs, '<g>', lens_tints]
    for r in range(rows):
        c_lo, c_hi = _row_span(r)
        for c in range(cols):
            v = fval(r, c)
            cx, cy = center(r, c)
            dpos = f'data-r="{r}" data-c="{c}"'
            if not (c_lo <= c < c_hi):
                # outside the oval taper: present (hover/walk) but not drawn.
                parts.append(cell_shape(cx, cy, f'{dpos} fill="rgba(0,0,0,0)"'))
                continue
            if v is None:
                dash = ' stroke-dasharray="2 2"' if pal["empty_dash"] else ''
                eop = 0.7 if pal["empty_dash"] else 0.28
                parts.append(cell_shape(
                    cx, cy, f'{dpos} fill="none" stroke="var(--line)" '
                    f'stroke-width="1" opacity="{eop}"{dash}'))
                continue
            op = _rank_opacity(v, ranked, lower_better)
            cell_title = esc(f"row {r}, col {c}: {v:.2f} {metric}")
            parts.append(cell_shape(
                cx, cy, f'{dpos} fill="rgba({pal["cell"]},{op:.2f})" '
                f'stroke="var(--line)" stroke-width="1"', title=cell_title))
    parts.append('</g>')
    # deliberately no session-count dots and no history trail: they were mark types a
    # viewer could not decode. The map now carries only what reads at a glance: cost by
    # shade, where you are, and the direction to a cheaper setup.

    current = som_block.get("current_cell")
    cur_xy = None
    if current and len(current) == 2:
        cx, cy = center(current[0], current[1])
        cur_xy = (cx, cy)
        # "you" is a hex border on the cell (JS re-owns markers on interactive maps).
        if not js_arrow:
            parts.append(marker(cx, cy, "som-current", pal["cur_stroke"],
                                2.0 if compact else 2.8))

    gradient = som_block.get("gradient") or {}
    target = gradient.get("target_cell")
    arm_change = gradient.get("arm_change")
    tgt_xy = None
    if target and len(target) == 2 and cur_xy:
        sx, sy = cur_xy
        tx, ty = center(target[0], target[1])
        tgt_xy = (tx, ty)
        dx, dy = tx - sx, ty - sy
        dist = (dx * dx + dy * dy) ** 0.5
        if dist > 1e-6 and not js_arrow:
            # the arrow to a cheaper setup shows on the minis too, so "where is better"
            # reads even at marquee size.
            head, sw, tgap, sgap, hw = (5.0, 2.0, 6, 7, 3.0) if compact \
                else (9.0, 2.8, 13, 14, 4.7)
            ux, uy = dx / dist, dy / dist
            px, py = -uy, ux
            tip_x, tip_y = tx - ux * tgap, ty - uy * tgap
            base_x, base_y = tip_x - ux * head, tip_y - uy * head
            start_x, start_y = sx + ux * sgap, sy + uy * sgap
            if not compact:
                # a wide transparent line over the arrow so it is easy to hover.
                parts.append(f'<line class="som-arrow" x1="{start_x:.1f}" '
                             f'y1="{start_y:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" '
                             f'stroke="transparent" stroke-width="18" '
                             f'pointer-events="stroke"/>')
            parts.append(f'<line class="som-arrow" x1="{start_x:.1f}" '
                         f'y1="{start_y:.1f}" x2="{base_x:.1f}" y2="{base_y:.1f}" '
                         f'stroke="{pal["arrow"]}" stroke-width="{sw}" '
                         f'stroke-linecap="round"/>')
            l_x, l_y = base_x + px * hw, base_y + py * hw
            r_x, r_y = base_x - px * hw, base_y - py * hw
            parts.append(f'<polygon class="som-arrow" points="{tip_x:.1f},{tip_y:.1f} '
                         f'{l_x:.1f},{l_y:.1f} {r_x:.1f},{r_y:.1f}" fill="{pal["arrow"]}"/>')

    if not compact:
        def _pill(px, py, text, color):
            w = 6.6 * len(text) + 16
            return (f'<rect x="{px - w / 2:.1f}" y="{py - 9:.1f}" width="{w:.1f}" '
                    f'height="18" rx="9" fill="var(--paper)" stroke="{color}" '
                    f'stroke-width="1.2"/><text x="{px:.1f}" y="{py + 3.6:.1f}" '
                    f'text-anchor="middle" font-size="10.5" font-weight="700" '
                    f'fill="{color}">{esc(text)}</text>')

        def _label_y(cy):
            return cy - 18 if cy - 18 > pad_t + 4 else cy + 18
        if cur_xy:
            parts.append(_pill(cur_xy[0], _label_y(cur_xy[1]), "you", pal["cur_stroke"]))
        if tgt_xy and not js_arrow:
            parts.append(_pill(tgt_xy[0], _label_y(tgt_xy[1]), "cheaper", pal["arrow"]))
    if js_arrow or svg_id:
        # JS owns all live markers (hex outlines) and the arrow on interactive maps.
        parts.append('<g class="som-fx"></g>')
    parts.append(lens_labels)  # territory names on top, so they read over cells and overlays
    parts.append(you_mark)      # YOU: always-on, over any lens
    if cmeta:                   # BEST: always-on, JS fills it and reacts to the score arms
        parts.append('<g class="zbest"></g>')
    parts.append("</svg>")
    if compact:
        sub = (f'<div class="som-compact-s">{esc(subtitle)}</div>'
               if subtitle else '')
        return (f'<div class="som-compact">'
                f'<div class="som-compact-t">{esc(title)}</div>{sub}'
                f'<div class="som-wrap">{"".join(parts)}</div></div>')

    caption = ""
    if arm_change:
        if isinstance(arm_change, dict) and arm_change.get("tweak"):
            cap_text = str(arm_change["tweak"])
        elif isinstance(arm_change, dict):
            axis = arm_change.get("axis", "setup")
            frm, to = arm_change.get("from"), arm_change.get("to")
            cap_text = f"A cheaper cell nearby: {axis} {frm} to {to}."
        else:
            cap_text = str(arm_change)
        caption = f'<div class="measure">{esc(cap_text)}</div>'

    occupied = len(have)
    mean_field = sum(have) / len(have) if have else None
    window = som_block.get("field_window_days")
    sessions_mapped = som_block.get("sessions_mapped")

    def _money(x):
        return f"${x:,.0f}" if x >= 10 else f"${x:.1f}"

    metric_h = ("cost per KB of code you kept"
                if metric == "d_per_survkb" else esc(str(metric)))
    scale_note = (f"= {metric_h} ({_money(lo)} to {_money(hi)})"
                  if have else f"= {metric_h}")
    # the always-visible key: no one should need the collapsed detail to read the map.
    key = (
        '<div class="som-key" style="display:flex;flex-wrap:wrap;gap:16px;'
        'align-items:center;margin-top:10px;font-size:12px;color:var(--ink2)">'
        '<span style="display:inline-flex;align-items:center;gap:7px">cheaper'
        f'<i style="width:70px;height:11px;border-radius:6px;display:inline-block;'
        f'background:linear-gradient(90deg,rgba({pal["cell"]},0.12),'
        f'rgba({pal["cell"]},0.92))"></i>costlier</span>'
        f'<span>{scale_note}</span>'
        f'<span><b style="color:{pal["cur_stroke"]};font-size:15px">◉</b> you</span>'
        + (f'<span><b style="color:{pal["arrow"]};font-size:15px">→</b> '
           f'a cheaper setup you already use</span>' if target else '')
        + '</div>')

    if legend_bits is None:
        legend_bits = [
            "Each hexagon is one way you run your setup (which model, how much "
            "review, how many agents in parallel). Similar setups sit next to each "
            "other, so the map is a landscape, not a table.",
            "A hexagon's shade is how much that setup costs per KB of code that "
            "survived: pale is cheap, dark is expensive. Empty hexes are setups you "
            "have not used lately.",
            "You are at the ring; the arrow points to a nearby setup that costs less "
            "and that you already use sometimes.",
        ]
    raw = ((f"mean cost {mean_field:.2f}" if mean_field is not None
           else "mean cost n/a") +
          f", {occupied}/{rows * cols} setups used, "
          f"{window if window is not None else 'n/a'} day window" +
          (f", {sessions_mapped} sessions mapped"
           if sessions_mapped is not None else ""))
    legend = (f'<details class="breakdown"><summary>more detail</summary>'
             f'<p class="fine">{" ".join(legend_bits)}</p>'
             f'<p class="fine">{esc(raw)}</p></details>')

    return (f'<h2>{esc(title)} <span class="sub">{esc(subtitle)}</span></h2>'
           f'<div class="som-wrap">{"".join(parts)}</div>{key}{caption}{legend}')


def render_shared_map(merged, current_cell, gradient, style="classic"):
    """The federated shared frontier (item C): the peer-validated cost field merged
    across operators, with YOUR cell on it and the support-weighted arrow to the
    cheaper, corroborated region. Reuses render_som_map: no personal trajectory (the
    field is everyone's), a shared-frontier title and legend. Pure; returns '' when
    there is no merged map. Additive: absence renders nothing."""
    if not merged:
        return ""
    lattice = merged.get("lattice") or {}
    if not lattice.get("rows") or not lattice.get("cols"):
        return ""
    g = gradient or {}
    target = g.get("target_cell")
    arm_change = None
    if target and current_cell:
        delta = g.get("delta")
        sup = g.get("support")
        contrib = g.get("contributors")
        piece = (f"about ${delta:.2f} cheaper per KB kept"
                 if isinstance(delta, (int, float)) else "cheaper")
        arm_change = {"tweak": (
            f"The frontier: a setup {piece}, backed by {sup} peer sessions across "
            f"{contrib} operators.")}
    # a som-block shaped view the drawing understands: field + support + your cell +
    # the frontier arrow. No trajectory: the field is the whole federation's, not a walk.
    block = {"lattice": lattice,
             "field": merged.get("field"),
             "support": merged.get("support"),
             "field_metric": merged.get("field_metric", "d_per_survkb"),
             "field_lower_is_better": merged.get("field_lower_is_better", True),
             "field_window_days": None,
             "sessions_mapped": sum(x for row in (merged.get("support") or [])
                                    for x in row),
             "current_cell": current_cell,
             "gradient": {"arm_change": arm_change, "target_cell": target,
                          "vector": g.get("vector")}}
    legend_bits = [
        "Same map, but the shade is the cost pooled across many operators, not just "
        "you. Everyone assigns their work to the same hexagons, so the costs add up "
        "honestly without anyone sharing their logs.",
        "Pale is cheap, dark is expensive. Empty hexes are setups no one reported "
        "lately.",
        "You are at the ring; the arrow points to the cheaper setup the wider group "
        "confirms, weighted by how much real work backs it.",
    ]
    return render_som_map(block, title="The shared frontier",
                          subtitle="the same map, cost pooled across operators, no logs shared",
                          legend_bits=legend_bits, style=style)


_WALK_CSS = (
    '<style>'
    '.lens-bar{display:flex;align-items:center;gap:6px;margin-top:14px}'
    '.lens-bar .lens-cue{font-size:10px;font-weight:700;letter-spacing:.09em;'
    'text-transform:uppercase;color:var(--muted);margin-right:2px}'
    '.lens-btn{font:inherit;font-size:11px;letter-spacing:.02em;cursor:pointer;'
    'padding:3px 10px;border:1px solid var(--line);border-radius:999px;'
    'background:transparent;color:var(--ink2);transition:all .1s}'
    '.lens-btn:hover{border-color:var(--muted)}'
    '.lens-btn.on{background:var(--ink);color:var(--card);border-color:var(--ink)}'
    '.lens-legend{display:inline-flex;align-items:center;gap:11px;margin-left:8px;'
    'font-size:11px;color:var(--ink2)}'
    '.lens-legend span{display:inline-flex;align-items:center;gap:5px}'
    '.lens-legend i{width:10px;height:10px;border-radius:2px;display:inline-block}'
    '.civ-wrap{margin-top:12px;position:relative}'
    # the per-cell reading floats AT the hovered cell (a Civ-V tile tooltip), so you never
    # scan away from where you are pointing. Pointer-transparent so it never blocks the hover.
    '.civ-tip{position:absolute;z-index:30;pointer-events:none;left:0;top:0;max-width:250px;'
    'background:var(--card);border:1px solid var(--line);border-radius:9px;padding:9px 11px;'
    'font-size:12px;line-height:1.5;color:var(--ink2);box-shadow:0 8px 24px rgba(0,0,0,.42);'
    'opacity:0;visibility:hidden;transition:opacity .08s}'
    '.civ-tip.on{opacity:1;visibility:visible}'
    # the pointed cell gets a bright outline so it is obvious which hex the tip describes.
    '.civ-cell{cursor:pointer}'
    '.civ-cell:hover{stroke:#EDEDF2;stroke-width:2.6;stroke-opacity:.95}'
    '.civ-tip .tt{font-weight:800;color:var(--ink);display:block;margin-bottom:3px}'
    '.civ-tip b{color:var(--ink);font-variant-numeric:tabular-nums}'
    '.civ-tip .tc{color:#6FD6C9}'
    '.civ-legend{display:flex;flex-wrap:wrap;gap:16px;margin-top:12px;font-size:12px;'
    'color:var(--ink2);align-items:center}'
    '.civ-legend>span{display:inline-flex;align-items:center;gap:6px}'
    '.civ-legend i{width:12px;height:12px;border-radius:3px;display:inline-block;'
    'border:2px solid transparent}'
    '.civ-legend .civ-best b{color:#4FB07E}'
    '.civ-note{font-size:11px;color:var(--muted);margin-top:7px;line-height:1.4;max-width:60ch}'
    '.som-maps-row{display:flex;flex-wrap:wrap;gap:24px;margin-top:10px}'
    '.som-maps-row>div{flex:1 1 300px;min-width:0}'
    '.fp-panel{flex:1 1 300px;min-width:0}'
    '.fp-label{font-size:11px;font-weight:700;letter-spacing:.03em;text-transform:uppercase;'
    'margin-bottom:5px;min-height:14px}'
    '.fp-cap{font-size:12px;line-height:1.4;color:var(--ink2);margin-top:7px}'
    '.som-compact-t{font-size:11px;font-weight:700;letter-spacing:.04em;'
    'text-transform:uppercase;color:var(--muted);margin-bottom:2px}'
    '.som-compact-s{font-size:11px;color:var(--muted);margin-bottom:5px}'
    '.som-cell{transition:opacity .08s}'
    '#wave-svg .wv-gen,#wave-svg .wv-hit{cursor:pointer}'
    '.vb-detail .mk-vs{color:var(--muted);margin:0 5px;font-style:italic}'
    '.walk{margin-top:12px}'
    '.walk-detail{font-size:13px;color:var(--ink2);min-height:38px;padding:9px 12px;'
    'border:1px solid var(--line);border-radius:8px;background:var(--paper)}'
    '.walk-detail .wd-h{font-weight:700;color:var(--rust);margin-right:6px}'
    '.walk-scrub-row{display:flex;align-items:center;gap:12px;margin-top:9px}'
    '.walk-scrub-row input[type=range]{flex:1;accent-color:var(--teal)}'
    '.walk-scrub-label{font-size:12px;color:var(--muted);'
    'font-variant-numeric:tabular-nums;white-space:nowrap}'
    '</style>')

_EFFORT_ORDER = {"low": 0, "medium": 1, "high": 2, "xhigh": 3, "max": 4}


def _arm_phrase(arm_change):
    """A plain, directional reading of the recommended move, e.g. 'Lower orchestrator
    firepower from opus-4-8 to sonnet-5'. '' when it cannot be phrased."""
    if not isinstance(arm_change, dict):
        return ""
    axis, frm, to = arm_change.get("axis"), arm_change.get("from"), arm_change.get("to")
    if not (axis and frm and to):
        return ""
    if axis in ("orchestrator", "worker"):
        name = f"{axis} firepower"
        lower = _FIRE.get(to, 0.5) < _FIRE.get(frm, 0.5)
    elif axis == "effort":
        name = "reasoning effort"
        lower = _EFFORT_ORDER.get(to, 0) < _EFFORT_ORDER.get(frm, 0)
    else:
        name, lower = axis, True
    return f"{'Lower' if lower else 'Raise'} {name} from {frm} to {to}"


_WALK_JS = r"""<script>
(function(){
  var CELLS=__CELLS__, BEST=__BEST__, PERIODS=__PERIODS__, ERAS=__ERAS__, CUR=__CUR__, AGG=__AGG__;
  var svg=document.getElementById('map-civ');
  if(!svg) return;  // the single Civ-V fingerprint
  var GEO={cell:+svg.getAttribute('data-cell'),hstep:+svg.getAttribute('data-hstep'),
           vstep:+svg.getAttribute('data-vstep'),pad:+svg.getAttribute('data-pad'),
           rr:+svg.getAttribute('data-rr')};
  var zciv=svg.querySelector('.zciv');
  var vbScore=document.getElementById('vb-score'), vbLabel=document.getElementById('vb-label'),
      vbRec=document.getElementById('vb-rec'), vbDetail=document.getElementById('vb-detail');
  var OBJC={eff:'var(--accent)',flow:'var(--teal)',simp:'var(--good)'},
      OBJN={eff:'efficiency',flow:'flow',simp:'simplicity'};
  var MID=' · ', ARR=' › ', REC='→', MK=['eff','flow','simp'];
  var cmap={}; CELLS.forEach(function(c){cmap[c.r+','+c.c]=c;});
  function cell(r,c){return cmap[r+','+c];}
  // Civ-V map geometry: compute a cell centre and hexagon directly (the map has no per-cell
  // data-r/data-c nodes, unlike the old SOM grid).
  var CIVA=[90,150,210,270,330,30];
  function ctr(r,c){return {x:GEO.pad+GEO.cell/2+c*GEO.hstep+((r%2)?GEO.hstep/2:0),
                            y:GEO.pad+GEO.cell/2+r*GEO.vstep, r:GEO.rr};}
  function hexAt(cx,cy){var p=[];for(var k=0;k<6;k++){var a=CIVA[k]*Math.PI/180;
    p.push((cx+GEO.rr*Math.cos(a)).toFixed(1)+','+(cy-GEO.rr*Math.sin(a)).toFixed(1));}return p.join(' ');}
  function money(v){return v==null?'n/a':(v<10?'$'+(+v).toFixed(1):'$'+Math.round(v));}
  function setup(c){if(!c)return 'an unused setup';
    var w=(c.worker&&c.worker!=='solo')?(ARR+c.worker):'';return c.engine+MID+c.model+w+MID+c.effort;}
  function rng(k){var vs=CELLS.map(function(c){return c[k];}).filter(function(v){return v!=null;});
    return vs.length?{lo:Math.min.apply(null,vs),hi:Math.max.apply(null,vs)}:null;}
  var R={eff:rng('eff'),flow:rng('flow'),simp:rng('simp')};
  function nrm(c,k){var r=R[k];if(!r||c[k]==null)return null;return (c[k]-r.lo)/((r.hi-r.lo)||1);}
  // full coverage: a cell scores only if it has every enabled dimension; a missing
  // dimension disqualifies it rather than being silently dropped (mirrors _recommend_cells).
  function good(c,en){var prod=1,cnt=0,miss=false;MK.forEach(function(m){if(!en[m])return;var x=nrm(c,m);if(x==null){miss=true;return;}prod*=Math.max(x,.001);cnt++;});return (miss||!cnt)?null:Math.pow(prod,1/cnt);}
  // selection is chosen server-side (support-weighted, full-coverage, noise-gated);
  // best() is the argmax cell (also the scrub's optimal reference); recOk() says whether
  // a confident move to it exists (gain beats the noise from support).
  function bkey(en){return MK.filter(function(m){return en[m];}).join(',');}
  function best(en){var b=BEST[bkey(en)];return (b&&b.cell)?cell(b.cell[0],b.cell[1]):null;}
  function recOk(en){var b=BEST[bkey(en)];return !!(b&&b.ok);}
  function objColor(en){var on=MK.filter(function(m){return en[m];});return on.length===1?OBJC[on[0]]:'var(--rust)';}
  function objName(en){var on=MK.filter(function(m){return en[m];});return on.length===3?'balance':(on.length===1?OBJN[on[0]]:on.map(function(m){return OBJN[m];}).join('+'));}
  function hexMk(r,c,color,sw){var p=pts(r,c);return p?('<polygon points="'+p+'" fill="none" stroke="'+color+'" stroke-width="'+sw+'"/>'):'';}
  function arrowSvg(a,b,color){if(!a||!b)return '';var dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy);if(d<1)return '';
    var ux=dx/d,uy=dy/d,px=-uy,py=ux,h=7;var tx=b.x-ux*(b.r+2),ty=b.y-uy*(b.r+2),bx=tx-ux*h,by=ty-uy*h,sx=a.x+ux*(a.r+2),sy=a.y+uy*(a.r+2);
    return '<line x1="'+sx+'" y1="'+sy+'" x2="'+bx+'" y2="'+by+'" stroke="'+color+'" stroke-width="2.4" stroke-linecap="round"/><polygon points="'+tx+','+ty+' '+(bx+px*3.6)+','+(by+py*3.6)+' '+(bx-px*3.6)+','+(by-py*3.6)+'" fill="'+color+'"/>';}
  function fmt(n){return (+n).toLocaleString();}
  function fmtv(m,v){if(v==null)return 'n/a';if(m==='eff')return ''+v;if(m==='simp')return ''+Math.round(v);return ''+(Math.round(v*10)/10);}
  function tog(m){return document.querySelector('.mtog[data-m="'+m+'"]');}
  // Two comparison selections drive the twin fingerprints: A (left, held by a click) and B
  // (right, follows the hover). Default: A = previous generation, B = current generation.
  // A selection is {era:id} (a generation cloud) or {day:i} (one sampled day).
  var EN={eff:true,flow:true,simp:true}, PV=null;
  function eraById(id){for(var i=0;i<ERAS.length;i++){if(ERAS[i].era===id)return ERAS[i];}return null;}
  var curEraId=(ERAS.length?ERAS[ERAS.length-1].era:null);
  var prevEraId=(ERAS.length>1?ERAS[ERAS.length-2].era:curEraId);
  var selA={era:prevEraId}, selB={era:curEraId}, HELD=false;
  var ACOL='#B0553A', BCOL='#3F6E66';  // panel identities: clay (A) and deep teal (B)
  function enSet(){var e={eff:EN.eff,flow:EN.flow,simp:EN.simp};if(PV)e[PV]=!e[PV];return e;}
  function selVals(s){if(s.day!=null){var p=PERIODS[s.day];return {eff:p.eff,flow:p.flow,simp:p.simp};}var g=eraById(s.era);return g?{eff:g.eff,flow:g.flow,simp:g.simp}:AGG;}
  function vals(){return selVals(selB);}
  function score(e,v){var s=1,any=false;MK.forEach(function(m){if(e[m]&&v[m]!=null){s*=v[m];any=true;}});return any?Math.round(s):0;}
  // daily bars fully opaque and uniform in front; a disabled metric fades right back.
  function dimWave(e){document.querySelectorAll('#wave-svg rect[data-m]').forEach(function(r){r.setAttribute('opacity', e[r.getAttribute('data-m')]?'1':'0.14');});}
  function selCells(s){if(s.day!=null){var dc=PERIODS[s.day].day_cell;return dc?[{r:dc[0],c:dc[1],w:1}]:[];}var g=eraById(s.era);return g?(g.cells||[]):[];}
  function selLabel(s){if(s.day!=null)return PERIODS[s.day].label;var g=eraById(s.era);return g?g.label:'';}
  function selKind(s){return s.day!=null?'sample':'generation';}
  function selEra(s){return s.era!=null?s.era:(s.day!=null&&PERIODS[s.day]?PERIODS[s.day].era:-1);}
  function selBars(s){var q=(s.day!=null)?('.wv-bar[data-i="'+s.day+'"]'):('.wv-bar[data-era="'+s.era+'"]');return [].slice.call(document.querySelectorAll('#wave-svg '+q));}
  // bars stay uniform; the two selected generations' bands light, the rest quiet; and the
  // A/B markers (clay/teal) show exactly what each selection is targeting.
  function emphasize(){var ws=document.getElementById('wave-svg');if(!ws)return;var ea=selEra(selA),eb=selEra(selB);
    ws.querySelectorAll('.wv-bar').forEach(function(gg){gg.setAttribute('opacity','1');});
    ws.querySelectorAll('.wv-band').forEach(function(bd){var e=+bd.getAttribute('data-era');bd.setAttribute('opacity',(e===ea||e===eb)?'0.5':'0.13');});
    ws.querySelectorAll('.wv-score').forEach(function(tx){var e=+tx.getAttribute('data-era');tx.setAttribute('opacity',(e===ea||e===eb)?'1':'0.4');});
    var fx=ws.querySelector('.wv-fx');if(fx)fx.innerHTML=selMarker(selA,ACOL)+selMarker(selB,BCOL);
    drawMerge();drawFlow();}
  // a day selection is marked by an outline around its bar; a generation by a colour bar on
  // top of its band. So you can always see whether you targeted a daily value or the band.
  function selMarker(sel,color){var ws=document.getElementById('wave-svg');if(!ws)return '';
    if(sel.day!=null){var bar=ws.querySelector('.wv-bar[data-i="'+sel.day+'"]');if(!bar)return '';var ht=bar.querySelector('.wv-hit');if(!ht)return '';
      var x=+ht.getAttribute('x'),y=+ht.getAttribute('y'),w=+ht.getAttribute('width'),hh=+ht.getAttribute('height');
      return '<rect x="'+(x-2).toFixed(1)+'" y="'+(y-2).toFixed(1)+'" width="'+(w+4).toFixed(1)+'" height="'+(hh+4).toFixed(1)+'" rx="4" fill="none" stroke="'+color+'" stroke-width="2.4"/>';}
    var bd=ws.querySelector('.wv-band[data-era="'+sel.era+'"]');if(!bd)return '';var b=bd.getBBox();
    return '<rect x="'+b.x.toFixed(1)+'" y="'+(b.y-4.5).toFixed(1)+'" width="'+b.width.toFixed(1)+'" height="2.8" rx="1.4" fill="'+color+'"/>';}
  // a smooth ribbon: cubic edges between (x0,ya..yb) at the source and (x1,ca..cb) at the
  // target. No square corners.
  function ribbon(x0,ya,yb,x1,ca,cb){var mx=(x0+x1)/2;
    return 'M'+x0.toFixed(1)+','+ya.toFixed(1)+' C'+mx.toFixed(1)+','+ya.toFixed(1)+' '+mx.toFixed(1)+','+ca.toFixed(1)+' '+x1.toFixed(1)+','+ca.toFixed(1)
      +' L'+x1.toFixed(1)+','+cb.toFixed(1)+' C'+mx.toFixed(1)+','+cb.toFixed(1)+' '+mx.toFixed(1)+','+yb.toFixed(1)+' '+x0.toFixed(1)+','+yb.toFixed(1)+' Z';}
  // the merge: each enabled metric flows from its stacked button on the left into a slice
  // of the score's left edge on the right, coloured by the metric. Toggling one off drops
  // its stream (and the score), so the number is visibly the product of these flows.
  function drawMerge(){var en=enSet(),v=vals();var tg=document.getElementById('topgroup'),mf=document.getElementById('merge-flow');
    if(!tg||!mf||!vbScore)return;var gr=tg.getBoundingClientRect();if(gr.width<1)return;
    mf.setAttribute('viewBox','0 0 '+gr.width.toFixed(1)+' '+gr.height.toFixed(1));
    var sr=vbScore.getBoundingClientRect();var sx=sr.left-gr.left,syc=(sr.top+sr.bottom)/2-gr.top,sh=sr.height*0.72;
    // widths are proportional to log(value): the score is a PRODUCT, and a product is a SUM
    // of logs, so in log space the three stream widths honestly add up to the whole.
    var on=MK.filter(function(m){return en[m]&&v[m]!=null;});
    var lg=on.map(function(m){return Math.log(Math.max(+v[m],1.0001));});
    var tot=lg.reduce(function(a,b){return a+b;},0)||1;
    var h='',cum=syc-sh/2;
    on.forEach(function(m,idx){var sl=sh*lg[idx]/tot,dyc=cum+sl/2;cum+=sl;
      var btn=document.querySelector('.mtog[data-m="'+m+'"]');if(!btn)return;
      var br=btn.getBoundingClientRect();var bx=br.right-gr.left,byc=(br.top+br.bottom)/2-gr.top;
      var bt=Math.min(sl,br.height*0.86)/2;
      h+='<path d="'+ribbon(bx,byc-bt,byc+bt,sx,dyc-sl/2,dyc+sl/2)+'" fill="'+OBJC[m]+'" opacity="0.34"/>';});
    // the "machine" that grinds them together: a small multiply node at the confluence, so
    // it reads as a product, not a plain additive flow.
    if(on.length>1){var nx=sx-8,ny=syc;
      h+='<circle cx="'+nx.toFixed(1)+'" cy="'+ny.toFixed(1)+'" r="8" fill="var(--card)" stroke="var(--muted)" stroke-width="1"/>'
        +'<path d="M'+(nx-3.2).toFixed(1)+','+(ny-3.2).toFixed(1)+' L'+(nx+3.2).toFixed(1)+','+(ny+3.2).toFixed(1)
        +' M'+(nx-3.2).toFixed(1)+','+(ny+3.2).toFixed(1)+' L'+(nx+3.2).toFixed(1)+','+(ny-3.2).toFixed(1)
        +'" stroke="var(--muted)" stroke-width="1.5" stroke-linecap="round"/>';}
    mf.innerHTML=h;}
  // connect each selection to the fingerprint panel that shows it: a soft ribbon (the sankey
  // idiom) from the selected slice of the timeline down into its panel below.
  function panelRibbon(sel,mapEl,color,hr){var bars=selBars(sel);if(!bars.length||!mapEl)return '';
    var L=1e9,R=-1e9,B=-1e9;bars.forEach(function(gg){var r=gg.getBoundingClientRect();L=Math.min(L,r.left-hr.left);R=Math.max(R,r.right-hr.left);B=Math.max(B,r.bottom-hr.top);});
    if(R-L<6){var mm=(L+R)/2;L=mm-4;R=mm+4;}
    var pr=mapEl.getBoundingClientRect();var pcx=(pr.left+pr.right)/2-hr.left,iw=pr.width*0.42,pL=pcx-iw/2,pR=pcx+iw/2,pT=pr.top-hr.top;
    var my=(B+pT)/2;
    return '<path d="M'+L.toFixed(1)+','+B.toFixed(1)+' C'+L.toFixed(1)+','+my.toFixed(1)+' '+pL.toFixed(1)+','+my.toFixed(1)+' '+pL.toFixed(1)+','+pT.toFixed(1)+' L'+pR.toFixed(1)+','+pT.toFixed(1)+' C'+pR.toFixed(1)+','+my.toFixed(1)+' '+R.toFixed(1)+','+my.toFixed(1)+' '+R.toFixed(1)+','+B.toFixed(1)+' Z" fill="'+color+'" opacity="0.15"/>';}
  // the up-flow: B's slice of the timeline flows UP into the centred score group, since B
  // is what the headline number reflects (the down-flows go to the fingerprints).
  function upRibbon(sel,color,hr){var bars=selBars(sel);if(!bars.length)return '';var tg=document.getElementById('topgroup');if(!tg)return '';
    var L=1e9,R=-1e9,T=1e9;bars.forEach(function(gg){var r=gg.getBoundingClientRect();L=Math.min(L,r.left-hr.left);R=Math.max(R,r.right-hr.left);T=Math.min(T,r.top-hr.top);});
    if(R-L<6){var mm=(L+R)/2;L=mm-4;R=mm+4;}
    var gr=tg.getBoundingClientRect();var gcx=(gr.left+gr.right)/2-hr.left,gw=gr.width*0.30,tL=gcx-gw/2,tR=gcx+gw/2,tB=gr.bottom-hr.top;var my=(tB+T)/2;
    return '<path d="M'+tL.toFixed(1)+','+tB.toFixed(1)+' C'+tL.toFixed(1)+','+my.toFixed(1)+' '+L.toFixed(1)+','+my.toFixed(1)+' '+L.toFixed(1)+','+T.toFixed(1)+' L'+R.toFixed(1)+','+T.toFixed(1)+' C'+R.toFixed(1)+','+my.toFixed(1)+' '+tR.toFixed(1)+','+my.toFixed(1)+' '+tR.toFixed(1)+','+tB.toFixed(1)+' Z" fill="'+color+'" opacity="0.13"/>';}
  // the sankey flows that tie the selectors to the readouts: B's timeline slice flows UP
  // into the score, and each selection flows DOWN into its fingerprint panel. Soft, low
  // opacity so it reads as atmosphere (glows on dark, stays faint on light), not a wall.
  function drawFlow(){var host=document.querySelector('.vibrant .card');if(!host)return;
    var ov=host.querySelector('.flow-ov');
    if(!ov){ov=document.createElementNS('http://www.w3.org/2000/svg','svg');ov.setAttribute('class','flow-ov');host.insertBefore(ov,host.firstChild);}
    var hr=host.getBoundingClientRect();if(hr.width<1)return;
    ov.setAttribute('viewBox','0 0 '+hr.width.toFixed(1)+' '+hr.height.toFixed(1));
    // the selected timeline slice flows UP into the score and DOWN into the map: the sankey
    // shows exactly which selection is driving YOU / BEST below.
    ov.innerHTML=upRibbon(selB,BCOL,hr)+panelRibbon(selB,document.getElementById('map-civ'),BCOL,hr);}
  // demoted in the comparison view: only a confident move shows, prefixed so it reads as
  // secondary advice about the current generation, not part of the A/B comparison.
  function setRec(e){if(!vbRec)return;var bc=best(e);
    if(bc&&recOk(e)){vbRec.innerHTML='to improve the current generation for '+objName(e)+': <span class="rec-arrow">'+REC+'</span> shift toward <b>'+setup(bc)+'</b>';return;}
    vbRec.innerHTML='';}
  function rigShort(c){if(!c)return '';var w=(c.worker&&c.worker!=='solo')?('›'+c.worker):'';return c.model+w+' · '+c.engine;}
  // YOU = your prevailing (heaviest) cell in the SELECTED slice; BEST = the best rig in that
  // slice for the enabled score arms, still required to carry your cargo (no bicycles). Both
  // vary with the timeline selection.
  function youOf(sel){var cs=selCells(sel);if(!cs.length)return CUR?{r:CUR[0],c:CUR[1]}:null;
    var p=cs[0];cs.forEach(function(c){if((c.w||0)>(p.w||0))p=c;});return {r:p.r,c:p.c};}
  function bestOf(sel,en){var cs=selCells(sel);if(!cs.length)return null;
    var y=youOf(sel),yc=(y?cell(y.r,y.c):null),yl=(yc&&yc.cargo)||0,best=null,bv=-1;
    cs.forEach(function(cc){var c=cell(cc.r,cc.c);if(!c)return;
      if(yl>0&&(c.cargo||0)<0.5*yl)return;                 // cargo rule: carry your load
      var g=good(c,en);if(g!=null&&g>bv){bv=g;best=c;}});
    if(!best){cs.forEach(function(cc){var c=cell(cc.r,cc.c);if(!c)return;var g=good(c,en);if(g!=null&&g>bv){bv=g;best=c;}});}
    return best;}
  function civStar(cx,cy){var p=[];for(var k=0;k<10;k++){var a=Math.PI/2+k*Math.PI/5,rd=(k%2?2.6:6.2);
    p.push((cx+rd*Math.cos(a)).toFixed(1)+','+(cy-rd*Math.sin(a)).toFixed(1));}return p.join(' ');}
  function markTxt(x,y,col,t){return '<text x="'+x.toFixed(1)+'" y="'+y.toFixed(1)+'" text-anchor="middle" font-size="12.5" font-weight="800" letter-spacing="0.1em" paint-order="stroke" stroke="var(--card)" stroke-width="3.5" stroke-linejoin="round" fill="'+col+'">'+t+'</text>';}
  function renderCivMarks(sel,en){if(!zciv)return;var vb=svg.viewBox.baseVal,h='',YC='#C56A4C',GB='#4FB07E',AR='#7FCBA6';
    var yy=youOf(sel),bc=bestOf(sel,en);var y=yy?ctr(yy.r,yy.c):null;
    var diff=(bc&&(!yy||bc.r!==yy.r||bc.c!==yy.c)),b=diff?ctr(bc.r,bc.c):null;
    if(y&&b){var dx=b.x-y.x,dy=b.y-y.y,d=Math.hypot(dx,dy)||1,ux=dx/d,uy=dy/d;
      var sx=y.x+ux*(y.r+3),sy=y.y+uy*(y.r+3),tx=b.x-ux*(b.r+3),ty=b.y-uy*(b.r+3),hx=tx-ux*10,hy=ty-uy*10,px=-uy,py=ux;
      h+='<line x1="'+sx.toFixed(1)+'" y1="'+sy.toFixed(1)+'" x2="'+hx.toFixed(1)+'" y2="'+hy.toFixed(1)+'" stroke="'+AR+'" stroke-width="2.6" stroke-linecap="round" stroke-dasharray="1 6" opacity="0.9"/>'
       +'<polygon points="'+tx.toFixed(1)+','+ty.toFixed(1)+' '+(hx+px*5).toFixed(1)+','+(hy+py*5).toFixed(1)+' '+(hx-px*5).toFixed(1)+','+(hy-py*5).toFixed(1)+'" fill="'+AR+'"/>';}
    if(b){var by=(b.y+b.r+16<vb.height-2)?(b.y+b.r+15):(b.y-b.r-9);
      h+='<polygon points="'+hexAt(b.x,b.y)+'" fill="'+GB+'" opacity="0.20"/><polygon points="'+hexAt(b.x,b.y)+'" fill="none" stroke="'+GB+'" stroke-width="3.4"/>'
       +markTxt(Math.min(Math.max(b.x,20),vb.width-20),by,GB,'BEST');}
    if(y){var ly=(y.y-y.r-9>12)?(y.y-y.r-9):(y.y+y.r+16);
      h+='<polygon points="'+hexAt(y.x,y.y)+'" fill="'+YC+'" opacity="0.22"/><polygon points="'+hexAt(y.x,y.y)+'" fill="none" stroke="'+YC+'" stroke-width="3.4"/>'
       +'<polygon points="'+civStar(y.x,y.y)+'" fill="'+YC+'"/>'+markTxt(Math.min(Math.max(y.x,20),vb.width-20),ly,YC,'YOU');}
    zciv.innerHTML=h;}
  // the OVERALL explanation (below the pair): the canonical meaning, once and short. The
  // per-print specifics are the two captions above it; the comparison is reading them.
  function detailHtml(e){var yy=youOf(selB),bc=bestOf(selB,e);
    var yc=yy?cell(yy.r,yy.c):null;var slice=(selB.day!=null?selLabel(selB):(selB.era===curEraId?'now':selLabel(selB)));
    var s='<b style="color:#C56A4C">&#9733; YOU</b> ('+slice+') mostly '+(yc?rigShort(yc):'n/a');
    if(bc){var same=(yy&&bc.r===yy.r&&bc.c===yy.c);
      s+=same?(' &mdash; already the <b style="color:#4FB07E">best</b> for '+objName(e)):
        (' &rarr; <b style="color:#4FB07E">BEST</b> for '+objName(e)+' is <b>'+rigShort(bc)+'</b>');}
    return s+'. Hover a territory to read a cell; use the timeline to change the slice.';}
  function refresh(){var e=enSet(),v=vals();
    if(vbScore)vbScore.textContent=fmt(score(e,v));
    MK.forEach(function(m){var b=tog(m);if(!b)return;b.setAttribute('aria-pressed',e[m]?'true':'false');var bb=b.querySelector('b');if(bb)bb.textContent=fmtv(m,v[m]);});
    if(vbLabel)vbLabel.textContent=(selB.day!=null?selLabel(selB)+' ':(selB.era===curEraId?'':'that generation '))+'score';
    dimWave(e);emphasize();renderCivMarks(selB,e);setRec(e);
    if(vbDetail)vbDetail.innerHTML=detailHtml(e);}
  // hovering a territory cell decodes exactly which rig it is. The reading floats AT the
  // cell (a tile tooltip), not in a caption below, so there is no vertical scan and you
  // always see what you are pointing at. The summary line below stays on YOU / BEST.
  var tip=document.getElementById('civ-tip'), wrap=svg.parentNode;
  function cellTip(c){
    if(!c)return '<span class="tt">unused setup</span>no sessions fell here';
    var co=(c.coord!=null)?('<div class="tc">coordination '+c.coord.toFixed(2)
      +(c.coord<0.05?' &middot; siloed':(c.coord>=0.5?' &middot; shared core':' &middot; some sharing'))+'</div>'):'';
    return '<span class="tt">'+setup(c)+'</span>'
      +'<div>'+(c.sessions||0)+' session'+(c.sessions==1?'':'s')+' &middot; <b>'+money(c.cost)+'</b> per KB</div>'
      +'<div>efficiency <b>'+(c.eff==null?'n/a':c.eff)+'</b> &middot; flow <b>'+(c.flow==null?'n/a':c.flow)
      +'</b> &middot; simplicity <b>'+(c.simp==null?'n/a':c.simp)+'</b></div>'+co;}
  function placeTip(cl){
    var wr=wrap.getBoundingClientRect(), cr=cl.getBoundingClientRect();
    var tw=tip.offsetWidth, th=tip.offsetHeight;
    var cx=cr.left+cr.width/2-wr.left, top=cr.top-wr.top-th-9;
    if(top<2){top=cr.bottom-wr.top+9;}
    var left=Math.max(4,Math.min(cx-tw/2,wr.width-tw-4));
    tip.style.left=left.toFixed(0)+'px';tip.style.top=top.toFixed(0)+'px';}
  svg.querySelectorAll('.civ-cell').forEach(function(cl){
    cl.addEventListener('mouseenter',function(){if(!tip)return;
      tip.innerHTML=cellTip(cell(cl.getAttribute('data-r'),cl.getAttribute('data-c')));
      tip.classList.add('on');placeTip(cl);});
    cl.addEventListener('mouseleave',function(){if(tip)tip.classList.remove('on');});});
  MK.forEach(function(m){var b=tog(m);if(!b)return;
    b.addEventListener('mouseenter',function(){PV=m;refresh();});
    b.addEventListener('mouseleave',function(){PV=null;refresh();});
    b.addEventListener('click',function(){var on=MK.filter(function(k){return EN[k];});if(EN[m]&&on.length<=1)return;EN[m]=!EN[m];PV=null;refresh();});});
  // the timeline drives the map: a bar targets a DAY, the band around it a GENERATION.
  // Hovering previews that slice into the map (YOU / BEST recompute); clicking HOLDS it so
  // you can read it (click the held slice again to release back to now).
  var wsvg=document.getElementById('wave-svg');
  function hitSel(t){if(!t||!t.classList)return null;
    if(t.classList.contains('wv-hit'))return {day:+t.parentNode.getAttribute('data-i')};
    if(t.classList.contains('wv-gen'))return {era:+t.getAttribute('data-era')};return null;}
  if(wsvg){
    wsvg.addEventListener('mouseover',function(ev){if(HELD)return;var s=hitSel(ev.target);if(s){selB=s;refresh();}});
    wsvg.addEventListener('click',function(ev){var s=hitSel(ev.target);if(!s)return;
      var same=(s.day!=null&&selB.day===s.day)||(s.era!=null&&selB.era===s.era);
      if(HELD&&same){HELD=false;selB={era:curEraId};}else{HELD=true;selB=s;}refresh();});
    wsvg.addEventListener('mouseleave',function(){if(!HELD){selB={era:curEraId};refresh();}});}
  window.addEventListener('resize',function(){drawMerge();drawFlow();});
  refresh();
})();
</script>"""


def _recommend_cells(cells, current_cell=None, support_k=4.0, noise_k=1.0,
                     cargo_floor=0.5):
    """For each non-empty objective subset of (eff, flow, simp): the best cell to move
    toward, and whether recommending that move is actually warranted. Four honesty
    rules keep the recommendation from chasing noise:

    - Cargo (the bicycle rule): efficiency is surviving work PER TOKEN, a scale-invariant
      ratio, so a lean rig that moved almost nothing can out-score the workhorse that
      carries your real load (a bicycle beats a truck on fuel per mile, but cannot haul
      the cargo). A cell is eligible only if it moved at least `cargo_floor` of the durable
      work (net surviving complexity) your CURRENT cell moves. A rig that has never carried
      your load is never advised as an upgrade. Skipped when the current cell has no cargo
      baseline or a cell lacks the field (older data), so it only ever tightens, never
      breaks.

    - Full coverage: a cell is eligible only if it has a value for EVERY enabled
      dimension. A missing dimension (e.g. a cell never babysitting-scored, so flow
      is None) is not a free pass; absence of data is not absence of a weakness. This
      is what a lone metric-maxing outlier used to exploit.
    - Confidence shrinkage: the selection score (normalized geometric mean) is scaled
      by n / (n + k), so a 2-session cell cannot outrank a well-supported one on a
      lucky reading.
    - Noise gate: the best cell's objective GAIN over the current cell must beat the
      noise implied by how thinly both cells are sampled (sigma * sqrt(1/n_best +
      1/n_cur), sigma = the spread of the objective across eligible cells). A move
      lost in that band is not surfaced as a call to action.

    Returns {subset_key: {"cell": [r, c] or None, "ok": bool}}. 'cell' is always the
    argmax (the scrub uses it as the optimal reference when replaying history); 'ok'
    is True only when a confident move exists: an eligible best cell, different from
    where you are, with a measurable current baseline and a gain that clears the
    noise. The card shows 'shift toward X' only when ok. subset_key is the enabled
    metric names in eff,flow,simp order, comma-joined (matching MK.filter().join).
    Note: per-cell eff/simp are still their dominant rig's git-attributed numbers, not
    the cell's own sessions; grounding those per-session is a separate, deeper change."""
    keys = ("eff", "flow", "simp")
    rng = {}
    for m in keys:
        vs = [c[m] for c in cells if c.get(m) is not None]
        rng[m] = (min(vs), max(vs)) if vs else None

    def nrm(c, m):
        r = rng[m]
        if r is None or c.get(m) is None:
            return None
        lo, hi = r
        return (c[m] - lo) / ((hi - lo) or 1)

    def raw(c, subset):
        # the normalized geometric-mean quality, unshrunk; None if any enabled dim
        # is missing (full coverage).
        prod = 1.0
        for m in subset:
            x = nrm(c, m)
            if x is None:
                return None
            prod *= max(x, 0.001)
        return prod ** (1.0 / len(subset))

    def pstdev(xs):
        if len(xs) < 2:
            return 0.0
        mu = sum(xs) / len(xs)
        return (sum((x - mu) ** 2 for x in xs) / len(xs)) ** 0.5

    cur = None
    if current_cell:
        want = list(current_cell)
        cur = next((c for c in cells if [c["r"], c["c"]] == want), None)

    # the bicycle rule: a candidate must carry a comparable load to where you are now.
    cur_cargo = cur.get("cargo") if cur else None

    def cargo_ok(c):
        if not cur_cargo or cur_cargo <= 0:
            return True  # no load baseline -> nothing to protect
        cc = c.get("cargo")
        if cc is None:
            return True  # cargo not measured for this cell (older data) -> do not exclude
        return cc >= cargo_floor * cur_cargo

    subsets = [("eff",), ("flow",), ("simp",), ("eff", "flow"), ("eff", "simp"),
               ("flow", "simp"), ("eff", "flow", "simp")]
    out = {}
    for subset in subsets:
        scored = [(c, raw(c, subset)) for c in cells
                  if (c.get("sessions") or 0) >= 2 and cargo_ok(c)]
        scored = [(c, g) for c, g in scored if g is not None]
        best_c, best_sel = None, -1.0
        for c, g in scored:
            n = c.get("sessions") or 0
            sel = g * (n / (n + support_k))  # confidence-shrunk selection score
            if sel > best_sel:
                best_sel, best_c = sel, c
        key = ",".join(subset)
        if best_c is None:
            out[key] = {"cell": None, "ok": False}
            continue
        cell_rc = [best_c["r"], best_c["c"]]
        g_cur = raw(cur, subset) if cur is not None else None
        ok = True
        if cur is None or g_cur is None:
            ok = False  # no measurable baseline: do not claim a confident move
        elif [cur["r"], cur["c"]] == cell_rc:
            ok = False  # already at the best cell
        else:
            sigma = pstdev([g for _, g in scored])
            n_b = best_c.get("sessions") or 1
            n_c = cur.get("sessions") or 1
            se = sigma * ((1.0 / n_b + 1.0 / n_c) ** 0.5)
            if (raw(best_c, subset) - g_cur) <= noise_k * se:
                ok = False  # gain lost in the noise implied by support
        out[key] = {"cell": cell_rc, "ok": ok}
    return out


def render_walk(report):
    """Emits the one self-contained script that drives the whole card: the metric
    toggles (hover to preview, click to hold) set which metrics feed the score and the
    descent; the waveform scrubs time; the fingerprint's arrow re-aims to the best cell
    for the enabled metrics; the recommendation sits below the fingerprints. The map and
    toggles live in the card (rendered elsewhere); this only wires them. '' when no walk."""
    som = (report.get("rig_space") or {}).get("som")
    if not som or not som.get("walk"):
        return ""
    cells = [{"r": m["cell"][0], "c": m["cell"][1], "eff": m.get("eff"),
              "flow": m.get("flow"), "simp": m.get("simp"), "cost": m.get("cost"),
              "engine": m.get("engine"), "model": m.get("model"),
              "worker": m.get("worker"), "effort": m.get("effort"),
              "cargo": m.get("cargo"), "coord": m.get("coord"),
              "sessions": m.get("sessions")}
             for m in som.get("cell_meaning", [])]
    tl, mb = report.get("topline") or {}, report.get("misery") or {}
    agg = {"eff": tl.get("eq"), "flow": mb.get("flow"), "simp": tl.get("simplicity")}

    # the card sits on the prevailing style of the latest era, not the last session's
    # noisy BMU, so "you" and the recommendation baseline match the map's motion.
    cur = _prevailing_current(report)

    def _safe(obj):
        return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")
    script = (_WALK_JS.replace("__CELLS__", _safe(cells))
              .replace("__BEST__", _safe(_recommend_cells(cells, cur)))
              .replace("__PERIODS__", _safe(_timeline_periods(report)))
              .replace("__ERAS__", _safe(_era_occupancy(report)))
              .replace("__CUR__", _safe(cur))
              .replace("__AGG__", _safe(agg)))
    return _WALK_CSS + script


def _card_maps(report):
    """ONE fingerprint, drawn as a Civ-V map: engine territories with borders, YOU fixed as
    your capital, and BEST plus the move drawn by JS so they react to the enabled score arms.
    The old two-panel A/B comparison is gone (it was redundant, and time already lives in the
    wave above); this single landscape map is the identity and the next move in one picture.
    Empty when the map is absent."""
    som = (report.get("rig_space") or {}).get("som")
    if not som:
        return ""
    civ = render_civ_map(som, svg_id="map-civ", compact=True)
    if not civ:
        return ""
    legend = ('<div class="civ-legend" id="civ-legend">'
              + "".join(f'<span><i style="background:{TERR[0]};border-color:{TERR[1]}"></i>'
                        f'{eng}</span>' for eng, TERR in _CIV_TERR.items())
              + f'<span class="civ-you"><b style="color:{_CIV_YOU}">&#9733;</b> you</span>'
              + '<span class="civ-best"><b>&#11041;</b> best rig for your target</span>'
              + f'<span><i style="background:{_CIV_COORD};border-color:{_CIV_COORD}"></i>'
              + 'coordination core (workers share files)</span></div>')
    note = ('<div class="civ-note">the coordination core is neutral: a brighter core is '
            'not "better", survival decides whether the sharing paid off. Hover any hex to '
            'read its rig.</div>')
    foot = ('<div class="vb-detail" id="vb-detail"></div>'
            '<div class="vb-rec" id="vb-rec"></div>')
    return (f'<div class="civ-wrap">{civ}<div class="civ-tip" id="civ-tip"></div></div>'
            f'{legend}{note}{foot}')


def render_shared_map_compact(merged, current_cell, subtitle=""):
    """The shared frontier as a compact marquee tile: the same lattice as your own
    map, shaded by the pooled field, with only your position marked. No arrow: the
    single recommendation lives under your map, so this tile stays a pure comparison
    backdrop (where you sit in everyone's terrain), not a second suggestion."""
    if not merged or not (merged.get("lattice") or {}).get("rows"):
        return ""
    block = {"lattice": merged["lattice"], "field": merged.get("field"),
             "support": merged.get("support"),
             "field_metric": merged.get("field_metric", "d_per_survkb"),
             "field_lower_is_better": merged.get("field_lower_is_better", True),
             "current_cell": current_cell,
             "gradient": {}}
    return render_som_map(block, style="ink-hex", compact=True,
                          title="The shared frontier", subtitle=subtitle)


def _combined_series(report):
    """Per-period efficiency, flow, simplicity and their product (the combined score),
    over the timeline, with missing components filled from the overall value so the
    waveform has no gaps. Newest last. [] when there is too little."""
    tline = report.get("timeline") or []
    over_flow = (report.get("misery") or {}).get("flow")
    over_simp = (report.get("topline") or {}).get("simplicity")
    # per-period simplicity is the same density measure as the topline: complexity per 1000
    # of that period's net-surviving lines. The timeline carries surviving as bytes (born -
    # killed), so convert with the corpus-wide bytes/line to keep the unit consistent.
    num = report.get("numerator") or {}
    surv_lines_all = num.get("total_surviving") or 0
    surv_bytes_all = (report.get("topline") or {}).get("surv_kb", 0) * 1024
    bpl = (surv_bytes_all / surv_lines_all) if surv_lines_all else 0
    out = []
    for r in tline:
        eq = r.get("eq")
        if eq is None:
            continue
        mis = r.get("misery")
        flow = round(100 - mis, 1) if mis is not None else over_flow
        net_bytes = (r.get("born", 0) or 0) - (r.get("killed", 0) or 0)
        surv_lines = (net_bytes / bpl) if bpl and net_bytes > 0 else 0
        simp = _density_simplicity(_surviving_lines(r.get("complexity"), surv_lines)) or over_simp
        if flow is None or simp is None:
            continue
        out.append({"eq": eq, "flow": flow, "simp": simp,
                    "comb": eq * flow * simp, "label": r.get("week"),
                    "changes": r.get("changes")})
    return out


def _timeline_periods(report):
    """Per timeline period: the combined score and its three components, plus the cell
    to show on the map for that period. The cell is the PREVAILING style of the ERA the
    period sits in, NOT the period's own modal BMU. Eras are the same segments the
    efficiency line draws its 1/2/3 levels from (bounded by detected setup changes), so
    the map moves only when the operator actually changed how they work (a few times),
    not once per noisy bucket (the operator runs a stable mix of sessions every day, so
    per-bucket modes flicker even when nothing changed). Each period carries its era id.
    [] when too little."""
    s = _combined_series(report)
    if len(s) < 3:
        return []
    by_label = _walk_by_label(report)
    # era bounds: the same change-marked indices the efficiency chart segments on.
    n = len(s)
    change_idx = [i for i, b in enumerate(s) if b.get("changes") and 0 < i < n]
    bounds = [0] + change_idx + [n]
    era_of, prevailing_of = {}, {}
    for eid, (a, b) in enumerate(zip(bounds, bounds[1:])):
        if b <= a:
            continue
        # the prevailing style of the era: the WORK-weighted BMU across all its sessions
        # (a heavy orchestration outweighs quick solo blips), so a day-to-day wobble in the
        # mix does not move the map inside a stable era. Fall back to count if no work.
        w = Counter()
        for j in range(a, b):
            for (c, wk) in by_label.get(s[j]["label"], []):
                w[c] += wk
        if not any(w.values()):
            for j in range(a, b):
                for (c, _wk) in by_label.get(s[j]["label"], []):
                    w[c] += 1
        prevailing = list(w.most_common(1)[0][0]) if w else None
        for j in range(a, b):
            era_of[j] = eid
            prevailing_of[j] = prevailing
    out, last = [], None
    for i, b in enumerate(s):
        cell = prevailing_of.get(i) or last
        last = cell if cell is not None else last
        # the narrow, day-level position: this bucket's OWN work-weighted BMU (what the map
        # shows when you hover a single bar), distinct from the era's prevailing cell above.
        dcw = Counter()
        for (c, wk) in by_label.get(b["label"], []):
            dcw[c] += wk
        if not any(dcw.values()):
            for (c, _wk) in by_label.get(b["label"], []):
                dcw[c] += 1
        day_cell = list(dcw.most_common(1)[0][0]) if dcw else None
        out.append({"label": b["label"], "comb": round(b["comb"]),
                    "eff": b["eq"], "flow": b["flow"], "simp": b["simp"],
                    "cell": cell, "day_cell": day_cell, "era": era_of.get(i)})
    return out


def _walk_by_label(report):
    """The walk's per-session BMU cells bucketed by the timeline's granularity label,
    shared by the period and era-occupancy builders."""
    som = (report.get("rig_space") or {}).get("som") or {}
    gran = ((report.get("fuel_and_work") or {}).get("granularity")) or "week"
    by_label = defaultdict(list)
    for w in (som.get("walk") or []):
        if w.get("day"):
            by_label[_bucket(w["day"], gran)[1]].append((tuple(w["cell"]), w.get("work", 0)))
    return by_label


def _era_occupancy(report):
    """Per era (generation), the CLOUD of cells the operator occupied, weighted by how
    many sessions landed in each: this is what the map shows when you click to hold a
    generation. cells is sorted heaviest first; w is the count normalized to the era's
    busiest cell (drives border weight/opacity in the client), n the raw count. Also the
    era's mean components and combined score, its date span, and how many sessions it
    holds. Eras align with the same change-marked segmentation the wave and line use."""
    s = _combined_series(report)
    if len(s) < 3:
        return []
    by_label = _walk_by_label(report)
    n = len(s)
    change_idx = [i for i, b in enumerate(s) if b.get("changes") and 0 < i < n]
    bounds = [0] + change_idx + [n]
    out = []
    for eid, (a, b) in enumerate(zip(bounds, bounds[1:])):
        if b <= a:
            continue
        # prevalence is weighted by WORK (output tokens), not session count: a heavy
        # orchestration outweighs several quick solo blips, so "mostly X" and the ring
        # sizes reflect where the work went. Fall back to session count if an era carries
        # no work signal. Keep the raw session count (n / days) for display.
        work, cnt = Counter(), Counter()
        for j in range(a, b):
            for (c, wk) in by_label.get(s[j]["label"], []):
                work[c] += wk
                cnt[c] += 1
        weight = work if any(work.values()) else cnt
        span = b - a
        mE = sum(s[j]["eq"] for j in range(a, b)) / span
        mF = sum(s[j]["flow"] for j in range(a, b)) / span
        mS = sum(s[j]["simp"] for j in range(a, b)) / span
        mx = max(weight.values()) if weight else 1
        cells = [{"r": r, "c": c, "w": round(wv / mx, 3), "n": cnt[(r, c)]}
                 for (r, c), wv in sorted(weight.items(), key=lambda kv: (-kv[1], kv[0]))]
        out.append({"era": eid, "cells": cells,
                    "eff": round(mE, 2), "flow": round(mF, 1), "simp": round(mS, 1),
                    "score": round(mE * mF * mS), "days": sum(cnt.values()),
                    "label": (s[a]["label"] + " to " + s[b - 1]["label"]
                              if b - 1 > a else s[a]["label"]),
                    "prevailing": [cells[0]["r"], cells[0]["c"]] if cells else None})
    return out


def _prevailing_current(report):
    """Where the operator prevailingly works NOW: the prevailing cell of the latest era,
    so the card's 'you' marker and the recommendation baseline sit on the stable current
    style rather than the last single session's noisy BMU. Falls back to the raw
    current_cell when there is too little timeline."""
    p = _timeline_periods(report)
    if p and p[-1].get("cell"):
        return p[-1]["cell"]
    som = (report.get("rig_space") or {}).get("som") or {}
    return som.get("current_cell")


def _wave_norm(values):
    """Normalize to [0,1] against a robust range (min .. 85th percentile), so one spiky
    period does not flatten the wave; outliers saturate at 1."""
    srt = sorted(values)
    lo = srt[0]
    hi = srt[min(len(srt) - 1, int(0.85 * len(srt)))]
    rng = (hi - lo) or 1.0
    return [min(max((v - lo) / rng, 0.0), 1.0) for v in values]


def render_waveform(report):
    """The score over time on ONE line: a single audio-style waveform where each period
    is a mirrored bar whose height is the combined signal, split into three stacked
    color bands (efficiency, flow, simplicity). So the wave shape reads the combined
    trajectory and the colours inside read which component carried it. Empty when there
    is too little history."""
    s = _combined_series(report)
    if len(s) < 3:
        return ""
    esc = _html.escape
    nE = _wave_norm([b["eq"] for b in s])
    nF = _wave_norm([b["flow"] for b in s])
    nS = _wave_norm([b["simp"] for b in s])
    comps = [(nE, "var(--accent)"), (nF, "var(--teal)"), (nS, "var(--good)")]
    W, H = 700, 96
    cy = H / 2
    n = len(s)
    bw = W / n
    unit = (H * 0.9) / 3.0  # each component contributes up to `unit` of height
    comps = [(nE, "var(--accent)", "eff"), (nF, "var(--teal)", "flow"),
             (nS, "var(--good)", "simp")]
    totals = [sum(nrm[i] * unit for nrm, _, _ in comps) for i in range(n)]

    # the generations (same eras the map moves in and the line numbers 1/2/3): each
    # period's era, the era's mean amplitude, its combined score and span.
    change_idx = [i for i, b in enumerate(s) if b.get("changes") and 0 < i < n]
    bounds = [0] + change_idx + [n]
    era_id = [0] * n
    era_mean_seq = [0.0] * n
    escore, espan = {}, {}
    eid = 0
    for a, b in zip(bounds, bounds[1:]):
        if b <= a:
            continue
        span = b - a
        m = sum(totals[a:b]) / span
        mE = sum(s[j]["eq"] for j in range(a, b)) / span
        mF = sum(s[j]["flow"] for j in range(a, b)) / span
        mS = sum(s[j]["simp"] for j in range(a, b)) / span
        for j in range(a, b):
            era_id[j], era_mean_seq[j] = eid, m
        escore[eid], espan[eid] = round(mE * mF * mS), (a, b)
        eid += 1
    neras = eid

    def _smooth(seq, w=5):
        half, out = w // 2, []
        for i in range(len(seq)):
            lo, hi = max(0, i - half), min(len(seq), i + half + 1)
            out.append(sum(seq[lo:hi]) / (hi - lo))
        return out
    # the smoothed generational amplitude: the piecewise era means, softened across the
    # boundaries so the spine flows instead of stepping. This IS the centre line.
    g = _smooth(era_mean_seq, 5)

    def cx(i):
        return i * bw + bw / 2
    RT = 0.62  # ribbon half-thickness as a fraction of the smoothed amplitude: exaggerated,
    # so the band pokes past the average bar and reads as a legible coloured back trend
    # a muted, warm-leaning categorical palette for the generations, in the paper/ink/rust
    # family so it sits with the brand and stays clear of the daily blue/teal/green.
    GEN = ["#B0553A", "#C79A46", "#7C6A86", "#5E7E77", "#A56E5B", "#8A7A4E"]

    # a full-height hit target per GENERATION, behind everything: hovering the band area
    # (gaps, the label, above/below the bars) targets the whole generation.
    genhits = []
    for e in range(neras):
        a, b = espan[e]
        genhits.append(f'<rect class="wv-gen" data-era="{e}" x="{a * bw:.1f}" y="0" '
                       f'width="{(b - a) * bw:.1f}" height="{H}" fill="transparent" '
                       f'pointer-events="all"/>')

    wd = max(bw * 0.78, 0.8)
    bars = []
    for i in range(n):
        segs = [(nrm[i] * unit, color, m) for nrm, color, m in comps]
        total = totals[i]
        y = cy - total / 2
        x = i * bw
        bx = x + (bw - wd) / 2
        # the hit target is the BAR ITSELF (not full height): clicking the bar targets that
        # DAY; the decorative rects below never capture, so the band behind stays reachable.
        grp = [f'<g class="wv-bar" data-i="{i}" data-era="{era_id[i]}">'
               f'<rect class="wv-hit" x="{bx:.1f}" y="{cy - total / 2:.1f}" width="{wd:.1f}" '
               f'height="{max(total, 0.8):.1f}" fill="transparent" pointer-events="all"/>']
        for hgt, color, m in segs:
            if hgt >= 0.4:
                grp.append(f'<rect data-m="{m}" x="{bx:.1f}" y="{y:.1f}" '
                           f'width="{wd:.1f}" height="{hgt:.1f}" rx="2.5" fill="{color}" '
                           f'pointer-events="none"/>')
            y += hgt
        if total >= 0.8:
            grp.append(f'<rect x="{bx:.1f}" y="{cy - total / 2:.1f}" width="{wd:.1f}" '
                       f'height="{total:.1f}" rx="3" fill="url(#wgloss)" pointer-events="none"/>')
        grp.append('</g>')
        bars.append("".join(grp))

    # the exaggerated solid rollup: one bold band per generation, each its OWN colour, at
    # the smoothed generational amplitude. The daily bars ride over it (their e/f/s tips
    # poke past the band). Segments extend to the era boundaries so the colours abut into
    # one continuous multi-colour ribbon; the JS brightens the generation feeding the score.
    ribbons, labels, dividers = [], [], []
    for e in range(neras):
        a, b = espan[e]
        xl, xr = a * bw, b * bw
        pts = ([(xl, cy - g[a] * RT)] + [(cx(i), cy - g[i] * RT) for i in range(a, b)]
               + [(xr, cy - g[b - 1] * RT), (xr, cy + g[b - 1] * RT)]
               + [(cx(i), cy + g[i] * RT) for i in range(b - 1, a - 1, -1)]
               + [(xl, cy + g[a] * RT)])
        col = GEN[e % len(GEN)]
        ribbons.append(f'<polygon class="wv-band" data-era="{e}" points="'
                       + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
                       + f'" fill="{col}" opacity="1" pointer-events="none"/>')
        xm = (xl + xr) / 2
        gt = cy - max(g[i] for i in range(a, b)) * RT
        labels.append(f'<text class="wv-score" data-era="{e}" x="{xm:.1f}" '
                      f'y="{max(9.0, gt - 4):.1f}" text-anchor="middle" font-size="10.5" '
                      f'font-weight="700" fill="{col}" pointer-events="none">'
                      f'{_fmt_tok(escore[e])}</text>')
        if a > 0:
            dividers.append(f'<line x1="{xl:.1f}" y1="2" x2="{xl:.1f}" y2="{H - 2}" '
                            f'stroke="var(--ink)" stroke-width="1" stroke-dasharray="2 3" '
                            f'opacity="0.22"/>')
    # back to front: dividers, then the SOLID colour-per-generation rollup band (100%,
    # the backdrop), then the daily bars in FRONT (partly translucent, so the band shows
    # through the gaps between bars and reads as continuous), then the era scores.
    gloss = ('<defs><linearGradient id="wgloss" x1="0" y1="0" x2="0" y2="1">'
             '<stop offset="0" stop-color="#ffffff" stop-opacity="0.34"/>'
             '<stop offset="0.45" stop-color="#ffffff" stop-opacity="0.06"/>'
             '<stop offset="1" stop-color="#ffffff" stop-opacity="0"/></linearGradient></defs>')
    # hit targets (wv-gen) sit BEHIND the decorative band/bars; the daily bars' own hit
    # (wv-hit) sits on top of them. wv-fx (on top, non-interactive) holds the A/B markers.
    svg = (f'<svg id="wave-svg" viewBox="0 0 {W} {H}" role="img" aria-label="the combined '
           f'score over time: a bold colour-per-generation rollup band behind the daily '
           f'bars of efficiency, flow and simplicity, each generation labelled with its '
           f'score">{gloss}{"".join(genhits)}{"".join(dividers)}{"".join(ribbons)}'
           f'{"".join(bars)}{"".join(labels)}<g class="wv-fx" pointer-events="none"></g></svg>')
    note = ('<div class="wlegend"><span class="wl-key">'
            '<span><i style="background:var(--accent)"></i>efficiency</span>'
            '<span><i style="background:var(--teal)"></i>flow</span>'
            '<span><i style="background:var(--good)"></i>simplicity</span></span>'
            '<span class="wl-note">click a bar to hold a day, the band to hold a '
            'generation</span></div>')
    cap = ('<div class="wcap">score over time &middot; each shaded band is a rig '
           'generation, labelled with its score</div>')
    return (f'<div class="wave">{cap}{svg}{note}</div>')


def _som_mark():
    """The VIBRANT mark: a tiny hex SOM, like the 3dl logo, ink hexagons with one rust
    peak unit. Small, in place of the old three bars. Deterministic."""
    rr, ox, oy = 2.35, 3.0, 2.9
    hstep, vstep = rr * 1.732, rr * 1.5
    op = {(0, 0): 0.5, (0, 1): 0.28, (0, 2): 0.68, (1, 0): 0.34, (1, 1): 0.85,
          (1, 2): 0.44, (2, 0): 0.6, (2, 1): 0.38, (2, 2): 0.72}
    peak = (1, 2)
    hexes = []
    for (r, c), o in op.items():
        cx = ox + c * hstep + (hstep / 2 if r % 2 else 0)
        cy = oy + r * vstep
        pts = " ".join(f"{cx + rr * math.cos(math.radians(a)):.1f},"
                       f"{cy - rr * math.sin(math.radians(a)):.1f}"
                       for a in (90, 150, 210, 270, 330, 30))
        color = "var(--rust)" if (r, c) == peak else "var(--ink)"
        opacity = 1.0 if (r, c) == peak else o
        hexes.append(f'<polygon points="{pts}" fill="{color}" opacity="{opacity}"/>')
    w = ox + 2 * hstep + hstep / 2 + rr
    h = oy + 2 * vstep + rr
    return (f'<svg class="mark" viewBox="0 0 {w:.1f} {h:.1f}" aria-hidden="true">'
            f'{"".join(hexes)}</svg>')


def _hero_card(report):
    """The shareable scorecard, sparse by design: the VIBRANT wordmark, the hero
    number, the rig as a bar, a trend. Every element is a fact about the operator's
    own runs, so nothing here is falsifiable. The precise unit lives in the number's
    tooltip; the lever and advice live below in the detail. No share buttons, the
    card is the share."""
    esc = _html.escape
    tl = report["topline"]
    fp = report.get("fingerprint") or {}
    mb = report.get("misery")
    mark = _som_mark()
    # one headline number: the three meters were meaningless alone, so combine them
    # (efficiency x flow x simplicity). Absolute magnitude is arbitrary; the point is
    # its movement, which the waveform below shows. The three components ride along as
    # context and as their own waves.
    eff = tl["eq"]
    flow = (mb.get("flow", round(100 - mb["overall"], 1)) if mb else None)
    simp = tl.get("simplicity")

    def _tog(m, color, val, label, title=""):
        return (f'<button type="button" class="mtog" data-m="{m}" aria-pressed="true" '
                f'style="--oc:{color}"{f" title=\"{title}\"" if title else ""}>'
                f'<b>{val}</b> {label}</button>')
    comps = [_tog("eff", "var(--accent)", esc(str(eff)), "efficiency",
                  "durable shipped changes per Mtok, larger is better")]
    if flow is not None:
        comps.append(_tog("flow", "var(--teal)", f"{flow:g}", "flow"))
    if simp is not None:
        comps.append(_tog("simp", "var(--good)", f"{simp:.0f}", "simplicity"))
    if eff is not None and flow is not None and simp is not None:
        combined = round(eff * flow * simp)
        cv = f'{combined:,}'
    else:
        cv = esc(str(eff))
    # the controls sit stacked to the LEFT and each metric flows (a small sankey) into the
    # score on the RIGHT; the whole group is centred, and the active slice of the timeline
    # flows up into it from underneath. Flows are drawn by JS from live layout.
    hero = (f'<div class="combined"><div class="topgroup" id="topgroup">'
            f'<svg class="merge-flow" id="merge-flow" aria-hidden="true"></svg>'
            f'<div class="cparts" id="vb-parts">{"".join(comps)}</div>'
            f'<div class="score-col"><div class="cv" id="vb-score" '
            f'style="min-width:{len(cv)}ch" '
            f'title="the enabled metrics multiplied; toggle a metric to change it. '
            f'Watch it move, not its absolute size">{cv}</div>'
            f'<div class="cn" id="vb-label">score</div>'
            f'<div class="chint">the three meters multiplied; watch the trend, not the total</div>'
            f'</div>'
            f'</div></div>')
    _ = fp  # fingerprint data stays in report["fingerprint"]; the maps render it below
    return "".join([
        '<div class="card">',
        f'<div class="top"><div class="brand">{mark}VIBRANT</div>',
        f'<div class="meta">{tl.get("sessions")} sessions</div></div>',
        hero,
        render_waveform(report),
        _card_maps(report),
        '<div class="foot"><span>vibe-coding rig efficiency</span>'
        '<span>3dl-dev/vibrant</span></div>',
        '</div>'])


def _coverage_banner(report):
    """A blunt banner when the measured repos cover only a slice of the operator's
    sessions. The tool measuring 9% of a rig and reporting it as the whole was the
    failure; this makes the gap loud and names what to add."""
    cov = report.get("coverage")
    if not cov or cov.get("measured_pct") is None or cov["measured_pct"] >= 90:
        return ""
    esc = _html.escape
    top = ", ".join(f'{esc(u["proj"])} ({u["sessions"]})'
                    for u in cov.get("unmeasured", [])[:6])
    return (f'<div class="cov"><div class="cov-h">Partial coverage: '
            f'{cov["measured_pct"]}% of your sessions</div>'
            f'<div class="cov-b">This number is built from {cov["measured_sessions"]} '
            f'of {cov["total_sessions"]} sessions, the ones in the measured repos. '
            f'Your biggest unmeasured projects are {top}. Re-run with '
            f'<code>--repos auto</code> (or add them to <code>--repos</code>) so the '
            f'meter reflects your whole rig, not a slice.</div></div>')


def _lever_html(report):
    """The lever and measure line: the operator's advice, in the detail (not the
    shareable card, where a small tweak would read as an anticlimax)."""
    esc = _html.escape
    nav = report.get("navigation")
    lever = report.get("lever")
    measure = report.get("measure")
    out = []
    if nav:
        # steepest descent on the true-economy objective ($/surviving-work) over the
        # fingerprint. Visible is one line; the evidence + copy-paste prompt collapse.
        mis_note = ""
        if nav.get("from_misery") is not None and nav.get("to_misery") is not None:
            mis_note = (f" Misery goes {nav['from_misery']} to {nav['to_misery']}."
                        if nav["to_misery"] <= nav["from_misery"] else "")
        ev = (f"From your runs: your {nav['axis']} is {nav['from']} on "
              f"{nav['from_sessions']} sessions, at ${nav['from_cost']:.0f} per shipped "
              f"change; {nav['to']} runs at ${nav['to_cost']:.0f}, about "
              f"{nav['savings_pct']:.0f}% cheaper per change shipped.{mis_note} Dollars "
              f"per shipped change, so it prices the orchestrator's cache-read cost and "
              f"is not fooled by over-engineering (which inflates complexity, not the "
              f"count of changes).")
        prompt = (f"Change your default {nav['axis']} for this kind of work: use "
                  f"{nav['to']} instead of {nav['from']}. Your own runs ship a change "
                  f"for about {nav['savings_pct']:.0f}% less this way, at the same "
                  f"topology (keep delegating). Set it in your routing / CLAUDE.md, "
                  f"then re-run Vibrant with --baseline to confirm the move.")
        out.append(
            f'<div class="lever"><div class="lever-h">Your steepest move</div>'
            f'<div class="lever-tweak">{esc(nav["tweak"])}</div>'
            f'<details class="lever-more"><summary>why, and the prompt to apply it'
            f'</summary><div class="fine">{esc(ev)}</div>'
            f'<pre class="lever-prompt">{esc(prompt)}</pre></details></div>')
    elif lever:
        proof = str(lever.get("proof") or "unverified")
        verified = any(t in proof.lower()
                       for t in ("reproduced", "tier-2", "tier-3", "git-verif"))
        tweak = str(lever.get("tweak") or "")
        head, cls = ("Your biggest lever", "lever") if verified \
            else ("A lever to test", "lever warn")
        # the actionable artifact: a copy-paste prompt the operator hands their agent
        # to adopt the tweak as a standing rule, collapsed behind a disclosure so it is
        # inspectable but not in the way.
        prompt = (f"New standing rule for this rig, effective now: {tweak} "
                  f"Apply it on every relevant turn instead of your default, and add it "
                  f"to your project CLAUDE.md (or your orchestrator's system prompt) so "
                  f"it persists across sessions. Then re-run Vibrant with --baseline to "
                  f"confirm it moved the number.")
        prov = ("Reproduced on the frontier." if verified else
                f"Unverified frontier claim (proof: {esc(proof)}), so a hypothesis, not "
                f"a target: reproduce it or test it behind --baseline before trusting it.")
        out.append(
            f'<div class="{cls}"><div class="lever-h">{head}</div>'
            f'<div class="lever-tweak">{esc(tweak)}</div>'
            f'<details class="lever-more"><summary>prompt to apply it</summary>'
            f'<pre class="lever-prompt">{esc(prompt)}</pre>'
            f'<div class="fine">{prov}</div></details></div>')
    else:
        out.append('<div class="lever ok"><div class="lever-h">At the frontier</div>'
                   '<div class="lever-tweak">Nothing shaped like your setup beats you '
                   'yet. Contribute your result so the next person can learn.</div></div>')
    if measure:
        out.append(f'<div class="measure">Since last run: {measure["baseline_eq"]} to '
                   f'{measure["current_eq"]} ({measure["actual_delta"]:+}).</div>')
    return "".join(out)


def render_html(report):
    """Self-contained, theme-aware page: a shareable hero scorecard (number, stack,
    lever, trend) over the detail charts (efficiency over time, fuel-and-work small
    multiples, attribution). Stdlib string-building only, no external assets."""
    esc = _html.escape
    head = "<style>\n" + _CSS + "</style>\n"
    hero = _hero_card(report)
    # the interactive fingerprints, waveform and toggles all live in the card now;
    # render_walk emits just the script that drives them (the map is in the card).
    walk_js = render_walk(report)
    tl = [r for r in report.get("timeline", []) if r["eq"] is not None]
    if len(tl) < 2:
        body = (f'<div class="vibrant">{hero}{walk_js}{_coverage_banner(report)}'
                f'{render_small_multiples(report)}{render_attribution(report)}</div>')
        return _page(head + body)

    # the efficiency-over-time chart was retired: the waveform in the card carries the
    # generations now, so the separate chart was redundant. Only the breakdown remains.
    detail = ('<details class="breakdown"><summary>full breakdown: fuel streams and '
              'per-rig work</summary>'
              f'{render_small_multiples(report)}{render_attribution(report)}</details>')
    body = f'<div class="vibrant">{hero}{walk_js}{_coverage_banner(report)}{detail}</div>'
    return _page(head + body)


def _fmt_tok(n):
    if n >= 1e9:
        return f"{n / 1e9:.1f}B"
    if n >= 1e6:
        return f"{n / 1e6:.0f}M"
    if n >= 1e3:
        return f"{n / 1e3:.0f}k"
    return str(int(n))


def _sm_svg(rows):
    """The four-panel aligned small-multiples SVG for one fuel-and-work series."""
    esc = _html.escape
    panels = [
        ("cache_read_tok", "cache-read tokens", "var(--c-cacheread)", _fmt_tok),
        ("read_tok", "read tokens", "var(--c-read)", _fmt_tok),
        ("output_tok", "output tokens", "var(--c-output)", _fmt_tok),
        ("surv_kb", "net code retained (KB)", "var(--c-work)",
         lambda v: f"{v:,.0f}"),
    ]
    W, PH, GAP, ml, mr, mt = 760, 66, 26, 60, 16, 16
    n = len(rows)
    pw = W - ml - mr
    out = [f'<svg viewBox="0 0 {W} {mt + len(panels) * (PH + GAP)}" role="img" '
           f'aria-label="fuel and work over time">']

    def X(i):
        return ml + (pw * i / (n - 1) if n > 1 else pw / 2)

    for pi, (key, label, color, fmt) in enumerate(panels):
        top = mt + pi * (PH + GAP)
        vals = [r[key] for r in rows]
        vmax = max(vals) or 1

        def Y(v, top=top):
            return top + PH * (1 - v / vmax)
        out.append(f'<line x1="{ml}" y1="{top+PH}" x2="{ml+pw}" y2="{top+PH}" '
                   f'stroke="var(--grid)" stroke-width="1"/>')
        out.append(f'<text x="{ml}" y="{top-4}" font-size="11" font-weight="600" '
                   f'fill="var(--ink2)">{esc(label)}</text>')
        out.append(f'<text x="{ml+pw}" y="{top-4}" text-anchor="end" font-size="10" '
                   f'fill="var(--muted)">peak {esc(fmt(vmax))}</text>')
        area = f"{ml},{top+PH} " + " ".join(
            f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals)) + \
            f" {ml+pw},{top+PH}"
        out.append(f'<polygon points="{area}" fill="{color}" opacity="0.14"/>')
        line = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
        out.append(f'<polyline points="{line}" fill="none" stroke="{color}" '
                   f'stroke-width="2" stroke-linejoin="round"/>')
        for i, v in enumerate(vals):
            tip = f"{rows[i]['bucket']}: {fmt(v)} {label}"
            out.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="3" fill="{color}">'
                       f'<title>{esc(tip)}</title></circle>')
        if pi == len(panels) - 1:
            # thin x-labels to ~8 so a daily axis does not collide (matches the
            # efficiency chart); always keep the last so the range end is shown.
            lstep = max(1, round(n / 8))
            for i, r in enumerate(rows):
                if i % lstep and i != n - 1:
                    continue
                out.append(f'<text x="{X(i):.1f}" y="{top+PH+16:.0f}" '
                           f'text-anchor="middle" font-size="10" '
                           f'fill="var(--muted)">{esc(r["bucket"])}</text>')
    out.append("</svg>")
    return "".join(out)


# dimension id -> the fuel_and_work slice key and the human group label. One
# selector cuts by every fingerprint dimension the driver slices.
_SLICE_DIMS = [
    ("model", "by_model", "by orchestrator"),
    ("worker", "by_worker", "by worker"),
    ("model_roles", "by_model_roles", "by model roles"),
    ("effort", "by_effort", "by effort"),
    ("engine", "by_engine", "by engine"),
    ("routing", "by_routing", "by routing"),
    ("review_regime", "by_review_regime", "by review regime"),
    ("knowledge_practice", "by_knowledge_practice", "by knowledge practice"),
]


def render_small_multiples(report):
    """Fuel and work over time as aligned small multiples, with ONE interactive
    slicer that cuts by every fingerprint dimension (model / effort / engine /
    routing / review regime / knowledge practice), grouped by dimension. Each
    option shows a pre-rendered slice; slices with fewer than two non-empty buckets
    are dropped. Self-contained (inline JS toggling pre-rendered blocks, no external
    assets) -- honoring the stdlib/hoistable, ships-itself constraint."""
    fw = report.get("fuel_and_work") or {}
    rows = fw.get("series") or []
    esc = _html.escape
    if len(rows) < 2:
        return ""
    gran = fw.get("granularity", "week")
    blocks = [f'<div id="fw-all" class="fw-slice">{_sm_svg(rows)}</div>']
    groups = ['<option value="fw-all">All sessions</option>']
    idx = 0
    for dim_id, key, group_label in _SLICE_DIMS:
        opts = []
        for val, s in sorted((fw.get(key) or {}).items()):
            if len([b for b in s if b]) < 2:
                continue
            idx += 1
            bid = f"fw-{dim_id}-{idx}"
            blocks.append(f'<div id="{bid}" class="fw-slice" hidden>{_sm_svg(s)}</div>')
            opts.append(f'<option value="{bid}">{esc(str(val))}</option>')
        if opts:
            groups.append(f'<optgroup label="{esc(group_label)}">{"".join(opts)}'
                          f'</optgroup>')
    js = ("<script>(function(){var s=document.getElementById('fw-sel');if(!s)return;"
          "s.addEventListener('change',function(){"
          "document.querySelectorAll('.fw-slice').forEach(function(d){d.hidden=true;});"
          "var t=document.getElementById(s.value);if(t)t.hidden=false;});})();</script>")
    return (f'<h2>Fuel and work <span class="sub">token streams vs code that '
            f'survived</span> <select id="fw-sel">{"".join(groups)}</select></h2>'
            f'{"".join(blocks)}{js}')


def render_attribution(report):
    """The git<->session attribution (item 2) surfaced in the page: per model and
    per effort, the surviving lines / complexity / commits the join credited to
    each. A table, not a small-multiples panel -- it is a per-cell total, not a
    time series, so forcing it onto the shared time axis would be dishonest."""
    attr = ((report.get("numerator") or {}).get("attribution")) or {}
    if not attr.get("matched"):
        return ""
    esc = _html.escape

    # the second meter joins the by-rig table: each rig shows work AND misery, the
    # cost/bearability tradeoff in one row. Misery is keyed by the same rig string.
    mis = ((report.get("misery") or {}).get("by_model_roles")) or {}

    def table(title, first_col, d, mcol=None):
        head = "<th>misery</th>" if mcol else ""
        rows = ""
        for k, v in d.items():
            mc = (f"<td>{mcol.get(k)}</td>" if mcol and mcol.get(k) is not None
                  else ("<td></td>" if mcol else ""))
            rows += (f"<tr><td>{esc(str(k))}</td><td>{v['surviving']:,}</td>"
                     f"<td>{v['net_complexity']:,}</td><td>{v['commits']}</td>{mc}</tr>")
        return (f"<h2>{esc(title)}</h2><table><thead><tr><th>{esc(first_col)}</th>"
                f"<th>surviving lines</th><th>complexity</th><th>commits</th>{head}"
                f"</tr></thead><tbody>{rows}</tbody></table>")

    parts = []
    if attr.get("by_model_roles"):
        parts.append(table("Surviving work by rig (orchestrator to worker)",
                           "orchestrator to worker", attr["by_model_roles"],
                           mcol=mis))
    if attr.get("by_orchestrator"):
        parts.append(table("Surviving work by orchestrator (direct agent)",
                           "orchestrator", attr["by_orchestrator"]))
    if attr.get("by_effort"):
        parts.append(table("Surviving work by effort", "effort", attr["by_effort"]))
    note = (f'<p class="fine">Credited to the whole rig, never split below the session. '
            f'{attr["matched"]} commits joined, {attr.get("unmatched", 0)} unmatched.</p>')
    return "".join(parts) + note if parts else ""


def _page(inner):
    return ("<!doctype html><html><head><meta charset=utf-8>"
            "<meta name=viewport content=\"width=device-width,initial-scale=1\">"
            "<title>Vibrant: your efficiency over time</title></head>"
            f"<body>{inner}</body></html>\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--harness", default="claude-code")
    ap.add_argument("--repos", default="auto",
                    help="comma-separated repo paths, or 'auto' (default) to "
                         "discover them from the sessions in the snapshot")
    ap.add_argument("--repos-root", default="~/projects",
                    help="where auto-discovery looks for repos (default ~/projects)")
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--since", default="30.days.ago")
    ap.add_argument("--frontier", default=None,
                    help="frontier to compare against: a path or a URL "
                         "(http/https/file). Default: $VIBRANT_FRONTIER, else the "
                         "repo's frontier/reference-frontier.json")
    ap.add_argument("--now", type=float, default=None,
                    help="fixed epoch for deterministic age buckets; default clock")
    ap.add_argument("--baseline", default=None,
                    help="a prior report.json; show the actual EQ move since it")
    ap.add_argument("--labels", default=None,
                    help="fingerprint-labels.json (pattern dims per rig); default: "
                         "alongside the snapshot if present")
    ap.add_argument("--granularity", default="auto",
                    choices=["auto", "day", "week", "month"],
                    help="time bucket for the curves; auto picks day/week/month by span")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dump-sessions", default=None,
                    help="also write the per-session metric list here (SOM seam)")
    args = ap.parse_args()

    root = os.path.expanduser(args.repos_root)
    if args.repos.strip().lower() in ("", "auto"):
        repos = discover_repos(args.snapshot, root, args.since)
        print(f"auto-discovered {len(repos)} repo(s) from the snapshot: "
              f"{', '.join(os.path.basename(r) for r in repos)}", file=sys.stderr)
    else:
        repos = [os.path.expanduser(r) for r in args.repos.split(",") if r]
    coverage = coverage_for(args.snapshot, repos, root)
    # frontier resolution: explicit --frontier, else the operator's configured
    # $VIBRANT_FRONTIER (their team/org/public board), else the repo's own.
    frontier_ref = args.frontier or os.environ.get("VIBRANT_FRONTIER") or \
        os.path.join(ROOT, "frontier", "reference-frontier.json")
    report = build_report(args.snapshot, repos, args.since, frontier_ref,
                          args.harness, args.now,
                          baseline_path=os.path.expanduser(args.baseline)
                          if args.baseline else None,
                          granularity=args.granularity,
                          labels_path=os.path.expanduser(args.labels)
                          if args.labels else None,
                          dump_sessions_path=os.path.expanduser(args.dump_sessions)
                          if args.dump_sessions else None,
                          coverage=coverage)
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
