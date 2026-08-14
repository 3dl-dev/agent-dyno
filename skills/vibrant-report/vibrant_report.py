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
import datetime
import glob
import hashlib
import html as _html
import json
import os
import re
import sys
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "core"))

import survival_git  # noqa: E402  (core/survival_git.py, after path insert)
import horizon_attribute  # noqa: E402  (core/horizon_attribute.py, the commit<->session join)

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
    functionality = numerator.get("net_complexity", 0)
    eq = round(functionality / out_mtok, 2) if out_mtok else None
    return {"eq": eq,
            "unit": "surviving functionality (decision points) per Mtok output",
            "larger_is_better": True,
            "functionality": functionality, "output_mtok": round(out_mtok, 3),
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
                         ("effort", "effort")):
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


def timeline(metrics, all_fp=None, gran="week"):
    """Efficiency curve (surviving KB per Mtok output, the headline's unit) binned at
    `gran` (day / week / month), annotated with the operator's real, day-dated setup
    changes (detect_changes). A change flag sits on the bucket that contains its date
    and carries the exact date, so the claim is checkable.

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
    rows = []
    for k in sorted(buckets):
        cells = buckets[k]
        born = sum(c["born"] for c in cells)
        killed = sum(c["killed"] for c in cells)
        survc = born - killed
        survkb = survc / 1024 if survc > 0 else 0.0
        out_mtok = sum(c["out_tok"] for c in cells) / 1e6
        eq = round(survkb / out_mtok, 2) if out_mtok else None
        fp = {"engine": modal([c["engine"] for c in cells]),
              "orchestrator": modal([c["model"] for c in cells]),
              "effort": modal([c["effort"] for c in cells])}
        bs = babysitting(cells)
        # churn: the share of what the model wrote that it deleted or rewrote in
        # the same session. eq (surviving work per token) is blind to this, so a
        # high-churn era can look efficient while being a lot of motion for the
        # yield. Surfaced so the topline is never misread as quality.
        rows.append({"week": labels[k], "eq": eq,
                     "sessions": len(cells), "fingerprint": fp,
                     "changes": chg.get(k, []), "born": born, "killed": killed,
                     "churn_pct": round(100 * killed / born, 1) if born else None,
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
    ingested = ["topology", "routing", "orchestrator-model", "effort",
                "delivery-cadence"]
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


def attribute_work(repos, since, snapshot_dir, tail=900.0):
    """Join surviving git work to the (model, effort) that authored it.

    Leverages horizon_attribute.load_sessions for the project+time match (never
    hand-rolling it) and survival_git for per-commit surviving lines AND surviving
    complexity. A commit matches the session whose active window brackets its time
    (short tail tolerance); its surviving lines/complexity accrue to that session's
    model and effort. Deterministic: commit times are fixed at HEAD, session times
    are fixed in the snapshot; a commit matching no session is counted, not
    dropped. This is the durable 'whose committed logic lasted' cut."""
    by_model = defaultdict(lambda: {"commits": 0, "surviving": 0, "net_complexity": 0})
    by_effort = defaultdict(lambda: {"commits": 0, "surviving": 0, "net_complexity": 0})
    matched = unmatched = 0
    for repo in repos:
        repo_name = os.path.basename(os.path.normpath(repo))
        sessions = horizon_attribute.load_sessions(snapshot_dir, repo_name)
        if not sessions:
            continue
        commits = survival_git.window_commits(repo, since)
        if not commits:
            continue
        tracked = set(survival_git.git(repo, "ls-files").splitlines())
        paths = {p for c in commits.values() for p in c["paths"]} & tracked
        surviving, complexity = survival_git.surviving_by_commit(repo, paths)
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
            for agg, key in ((by_model, s["model"]), (by_effort, s["effort"])):
                a = agg[key]
                a["commits"] += 1
                a["surviving"] += surviving.get(sha, 0)
                a["net_complexity"] += complexity.get(sha, 0)
    return {
        "matched": matched, "unmatched": unmatched,
        "by_model": {k: by_model[k] for k in sorted(by_model)},
        "by_effort": {k: by_effort[k] for k in sorted(by_effort)},
    }


def build_report(snapshot_dir, repos, since, frontier_path, harness, now,
                 baseline_path=None, granularity="week", labels_path=None):
    session_cost, usage_field = load_adapter_cost(harness)
    sessions, turns, code, survival = load_snapshot(snapshot_dir)
    metrics = []
    for sid, s in sessions.items():
        m = session_metrics(s, turns, code, survival, session_cost, usage_field)
        if m:
            metrics.append(m)
    metrics.sort(key=lambda m: m["sid"])  # deterministic order

    # every session's fingerprint (not just survival-having ones), for dating the
    # operator's real setup changes over ALL their runs, not the survival subset.
    all_fp = sorted(
        ({"day": s.get("day"), "engine": engine_of(s),
          "model": base_model(s.get("model")),
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

    # numerator per repo -- reported in two units: surviving KB (volume) and DORA
    # changes (shipped units of work: merged PRs, not commits) with change failure
    # rate. Volume and throughput carry different signal.
    repo_rows = []
    tot_add = tot_surv = tot_ch = tot_fail = tot_cx = 0
    for repo in repos:
        r = survival_git.survival(repo, since, now=now)
        ch = survival_git.changes(repo, since, now=now)
        name = os.path.basename(os.path.normpath(repo))
        row = {"name": name, "changes": ch["changes"], "failed_changes": ch["failed"],
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
    numerator["attribution"] = attribute_work(repos, since, snapshot_dir)
    # resolve now for the now-dependent confounds (window overlap). Deterministic
    # when --now is passed; falls back to wall-clock per the determinism contract
    # ("same inputs, same day, same bytes").
    now_val = now if now is not None else \
        datetime.datetime.now(datetime.timezone.utc).timestamp()

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
    tline = timeline(metrics, all_fp, granularity)
    bs = babysitting(metrics)
    fuel = fuel_and_work(metrics, granularity)

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
            "frontier_sha256": hashlib.sha256(fbytes).hexdigest() if fbytes else None,
            "driver": "vibrant_report/1",
        },
        "governance": {
            "clean": True,
            "assert": "engine-craft only; no individual-vs-product, no person-vs-person",
            "constitution": "docs/governance.md",
        },
        "topline": tl,
        "fingerprint": fingerprint_summary(metrics, numerator),
        "babysitting": bs,
        "lever": lever,
        "measure": measure,
        "timeline": tline,
        "fuel_and_work": {
            "granularity": granularity, "series": fuel,
            "by_model": fuel_sliced(metrics, granularity, "model"),
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
    L.append(f"# Your setup: {tl['eq']} functionality per Mtok output")
    L.append("")
    cfr = tl.get("change_failure_rate")
    cfr_s = f" Change failure rate {cfr}% (DORA)." if cfr is not None else ""
    L.append(f"Larger is better. Surviving decision-logic (a complexity proxy) per "
             f"million tokens the model generated, over {tl['sessions']} sessions."
             f"{cfr_s} Nothing leaves your machine.")
    L.append("")
    if lever:
        L.append("## Your biggest lever")
        L.append("")
        L.append(f"{lever['tweak']}")
        L.append("")
        L.append(f"Setups shaped like yours ({lever['engine']}, {lever['effort']} "
                 f"effort) retain {lever['frontier_cell_efficiency']} surviving-KB "
                 f"per dollar, against your {lever['your_cell_efficiency']}. Adopt "
                 f"it, then re-run with --baseline to see whether the topline moved.")
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
 --good:#008300;--up:#008300;--down:#e34948;--shadow:20,19,16;
 font-family:system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
 color:var(--ink);background:var(--surface);max-width:760px;margin:0 auto;
 padding:28px 20px 40px;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])) .vibrant{
 color-scheme:dark;--surface:#141412;--card:#1c1b19;--ink:#f6f5f0;--ink2:#c7c5bb;
 --muted:#918e85;--line:#2e2d29;--grid:#2c2c2a;--axis:#3a3a36;--accent:#3987e5;
 --series:#3987e5;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;
 --c-cacheread:#3987e5;--c-read:#d95926;--c-output:#199e70;--c-work:#159015;
 --good:#199e70;--up:#199e70;--down:#e66767;--shadow:0,0,0;}}
:root[data-theme=dark] .vibrant{color-scheme:dark;--surface:#141412;--card:#1c1b19;
 --ink:#f6f5f0;--ink2:#c7c5bb;--muted:#918e85;--line:#2e2d29;--grid:#2c2c2a;
 --axis:#3a3a36;--accent:#3987e5;--series:#3987e5;--s1:#3987e5;--s2:#d95926;
 --s3:#199e70;--s4:#c98500;--s5:#d55181;--c-cacheread:#3987e5;--c-read:#d95926;
 --c-output:#199e70;--c-work:#159015;--good:#199e70;--up:#199e70;--down:#e66767;--shadow:0,0,0;}
.vibrant *{box-sizing:border-box;}
.vibrant .card{background:var(--card);border:1px solid var(--line);border-radius:18px;
 padding:30px 32px;box-shadow:0 1px 2px rgba(var(--shadow),.05),0 10px 34px rgba(var(--shadow),.07);}
.vibrant .top{display:flex;justify-content:space-between;align-items:center;margin:0 0 26px;}
.vibrant .brand{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:800;
 letter-spacing:.16em;color:var(--ink);text-transform:uppercase;}
.vibrant .brand .mark{width:17px;height:15px;flex:none;display:block;}
.vibrant .brand .mark rect{fill:var(--accent);}
.vibrant .meta{font-size:12px;color:var(--muted);letter-spacing:.02em;font-variant-numeric:tabular-nums;}
.vibrant .mid{display:flex;justify-content:space-between;align-items:flex-end;
 gap:20px 28px;flex-wrap:wrap;margin:0 0 20px;}
.vibrant .hero-left{min-width:0;}
.vibrant .num{font-size:82px;font-weight:730;letter-spacing:-.035em;line-height:.82;
 color:var(--accent);margin-top:2px;}
.vibrant .unit{font-size:13.5px;font-weight:600;color:var(--ink2);margin-top:16px;}
.vibrant .how{font-size:12px;color:var(--muted);margin-top:4px;}
.vibrant .hero-right{display:flex;flex-direction:column;align-items:flex-end;gap:5px;flex:none;}
.vibrant .row-h{font-size:10.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
 color:var(--muted);margin:0 0 9px;}
.vibrant .rig{margin:0 0 4px;}
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
.vibrant .lever-h{font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
 color:var(--muted);margin:0 0 6px;}
.vibrant .lever-tweak{font-size:15px;font-weight:600;color:var(--ink);line-height:1.4;}
.vibrant .lever-sub{font-size:12.5px;color:var(--ink2);margin-top:6px;line-height:1.45;}
.vibrant .spark{width:224px;height:58px;display:block;}
.vibrant .trend-cap{font-size:12.5px;color:var(--ink2);}
.vibrant .trend-cap .up{color:var(--up);font-weight:650;}
.vibrant .trend-cap .down{color:var(--down);font-weight:650;}
.vibrant .measure{font-size:12.5px;color:var(--ink2);margin:12px 0 0;}
.vibrant .foot{margin-top:24px;padding-top:15px;border-top:1px solid var(--line);
 font-size:11px;letter-spacing:.03em;color:var(--muted);display:flex;justify-content:space-between;}
.vibrant h2{font-size:14px;font-weight:650;color:var(--ink);margin:34px 0 3px;letter-spacing:-.01em;}
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
 .vibrant .num{font-size:50px;}.vibrant .trend{flex-wrap:wrap;gap:8px;}}
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


def _hero_card(report):
    """The shareable scorecard, sparse by design: the VIBRANT wordmark, the hero
    number, the rig as a bar, a trend. Every element is a fact about the operator's
    own runs, so nothing here is falsifiable. The precise unit lives in the number's
    tooltip; the lever and advice live below in the detail. No share buttons, the
    card is the share."""
    esc = _html.escape
    tl = report["topline"]
    fp = report.get("fingerprint") or {}
    eqs = [r["eq"] for r in report.get("timeline", []) if r["eq"] is not None]
    gran = (report.get("fuel_and_work") or {}).get("granularity", "week")
    unit = {"day": "days", "week": "weeks", "month": "months"}.get(gran, "points")
    trend = ""
    if len(eqs) >= 2:
        d = eqs[-1] - eqs[0]
        arrow, cls = ("&#9650;", "up") if d > 0 else (("&#9660;", "down") if d < 0 else ("&#126;", ""))
        span = f"{len(eqs)} {unit if len(eqs) != 1 else unit[:-1]}"
        trend = (f'<div class="hero-right">{_sparkline(eqs)}'
                 f'<div class="trend-cap"><span class="{cls}">{arrow}&#8202;'
                 f'{abs(d):.0f}</span> over {span}</div></div>')
    mark = ('<svg class="mark" viewBox="0 0 18 16" aria-hidden="true">'
            '<rect x="0" y="9" width="4" height="7" rx="1.3"/>'
            '<rect x="7" y="5" width="4" height="11" rx="1.3"/>'
            '<rect x="14" y="1" width="4" height="15" rx="1.3"/></svg>')
    p = ['<div class="card">',
         f'<div class="top"><div class="brand">{mark}VIBRANT</div>',
         f'<div class="meta">{tl.get("sessions")} sessions</div></div>',
         '<div class="mid"><div class="hero-left">',
         f'<div class="num" title="surviving functionality per Mtok output, '
         f'larger is better">{esc(str(tl["eq"]))}</div>',
         '<div class="unit">surviving work per Mtok</div>',
         '<div class="how">logic that survived in git, per million output tokens</div>',
         '</div>', trend, '</div>']
    topo = fp.get("orchestration_topology") or {}
    if topo.get("blend"):
        p.append('<div class="rig"><div class="row-h">Your rig</div>'
                 + _stack_bar(topo) + '</div>')
    p.append('<div class="foot"><span>vibe-coding rig efficiency</span>'
             '<span>3dl-dev/vibrant</span></div>')
    p.append('</div>')
    return "".join(p)


def _lever_html(report):
    """The lever and measure line: the operator's advice, in the detail (not the
    shareable card, where a small tweak would read as an anticlimax)."""
    esc = _html.escape
    lever = report.get("lever")
    measure = report.get("measure")
    out = []
    if lever:
        proof = str(lever.get("proof") or "unverified")
        verified = any(t in proof.lower()
                       for t in ("reproduced", "tier-2", "tier-3", "git-verif"))
        fce, yce = lever.get("frontier_cell_efficiency"), lever.get("your_cell_efficiency")
        if verified:
            head, cls = "Your biggest lever", "lever"
            sub = (f'A reproduced setup shaped like yours retains {fce} surviving-KB '
                   f'per dollar, against your {yce} (proof: {esc(proof)}). Re-run with '
                   f'--baseline to confirm the move on your own data.')
        else:
            # an unverified frontier cell is a hypothesis, not a target. Say so
            # plainly; an unsubstantiated number presented as advice is the instakill.
            head, cls = "A lever to test (unverified)", "lever warn"
            sub = (f'An <b>unverified</b> frontier claim (proof: {esc(proof)}) reports '
                   f'{fce} surviving-KB per dollar for a setup shaped like yours, against '
                   f'your {yce}. A self-reported cell is a hypothesis: reproduce it with '
                   f'the dynamometer, or test it behind --baseline, before you trust the '
                   f'number.')
        out.append(f'<div class="{cls}"><div class="lever-h">{head}</div>'
                   f'<div class="lever-tweak">{esc(str(lever.get("tweak") or ""))}</div>'
                   f'<div class="lever-sub">{sub}</div></div>')
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
    tl = [r for r in report.get("timeline", []) if r["eq"] is not None]
    if len(tl) < 2:
        body = (f'<div class="vibrant">{hero}{_lever_html(report)}'
                f'{render_small_multiples(report)}{render_attribution(report)}</div>')
        return _page(head + body)

    W, H = 760, 300
    ml, mr, mt, mb = 46, 18, 26, 40
    pw, ph = W - ml - mr, H - mt - mb
    eqs = [r["eq"] for r in tl]
    ylo, yhi = min(eqs), max(eqs)
    if yhi == ylo:
        yhi, ylo = yhi + 1, 0.0
    pad = (yhi - ylo) * 0.18
    # efficiency is non-negative; never let padding push the axis below zero.
    ylo, yhi = max(0.0, ylo - pad), yhi + pad
    n = len(tl)

    def X(i):
        return ml + (pw * i / (n - 1) if n > 1 else pw / 2)

    def Y(v):
        return mt + ph * (1 - (v - ylo) / (yhi - ylo))

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="efficiency over time">']
    for t in range(3):
        v = ylo + (yhi - ylo) * t / 2
        y = Y(v)
        parts.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{ml+pw}" y2="{y:.1f}" '
                     f'stroke="var(--grid)" stroke-width="1"/>')
        parts.append(f'<text x="{ml-8:.0f}" y="{y+4:.1f}" text-anchor="end" '
                     f'font-size="11" fill="var(--muted)">{v:.0f}</text>')
    parts.append(f'<line x1="{ml}" y1="{mt+ph}" x2="{ml+pw}" y2="{mt+ph}" '
                 f'stroke="var(--axis)" stroke-width="1"/>')
    # change-point indices split the run into configuration ERAS. Between two
    # changes the setup held roughly constant, so each era has a characteristic
    # efficiency: its mean. The bold line is those per-era means (a segmented
    # average that never smears across a real setup change), and the level SHIFT at
    # each change is the signal the daily noise otherwise buries. This is the
    # thesis made visible: an arrangement has a level, and tuning moves the level.
    change_idx = [i for i, r in enumerate(tl) if r["changes"]]
    bounds = [0] + change_idx + [n]
    eras = []
    for a, b in zip(bounds, bounds[1:]):
        if b > a:
            seg = eqs[a:b]
            born = sum(r.get("born") or 0 for r in tl[a:b])
            killed = sum(r.get("killed") or 0 for r in tl[a:b])
            churn = round(100 * killed / born) if born else None
            eras.append((a, b, sum(seg) / len(seg), churn))

    # flags: dashed verticals + numbered pins at each change
    flags, k = [], 0
    for i, r in enumerate(tl):
        if not r["changes"]:
            continue
        k += 1
        x = X(i)
        parts.append(f'<line x1="{x:.1f}" y1="{mt-4}" x2="{x:.1f}" y2="{mt+ph}" '
                     f'stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3" '
                     f'opacity="0.6"/>')
        parts.append(f'<circle cx="{x:.1f}" cy="{mt-4}" r="8" fill="var(--card)" '
                     f'stroke="var(--accent)" stroke-width="1.5"/>')
        parts.append(f'<text x="{x:.1f}" y="{mt-0.5}" text-anchor="middle" '
                     f'font-size="10" font-weight="700" fill="var(--accent)">{k}</text>')
        flags.append((k, r))

    # daily actuals, faint: the raw per-day truth under the trend, still hoverable
    dline = " ".join(f"{X(i):.1f},{Y(r['eq']):.1f}" for i, r in enumerate(tl))
    parts.append(f'<polygon points="{X(0):.1f},{mt+ph:.1f} {dline} {X(n-1):.1f},{mt+ph:.1f}" '
                 f'fill="var(--accent)" opacity="0.05"/>')
    parts.append(f'<polyline points="{dline}" fill="none" stroke="var(--accent)" '
                 f'stroke-width="1.3" stroke-linejoin="round" opacity="0.30"/>')
    for i, r in enumerate(tl):
        tip = f"{r['week']}: {r['eq']} survKB per Mtok, {r['sessions']} sessions"
        if r["changes"]:
            tip += " | " + "; ".join(r["changes"])
        parts.append(f'<circle cx="{X(i):.1f}" cy="{Y(r["eq"]):.1f}" r="2.2" '
                     f'fill="var(--accent)" opacity="0.34"><title>{esc(tip)}</title></circle>')

    # era-mean step line, bold: the readable signal. Each era also carries its
    # CHURN (share of written code deleted in-session), which eq is blind to, so a
    # high level bought with a lot of thrown-away work reads honestly.
    step = []
    for (a, b, mean, churn) in eras:
        x0, x1 = X(a), (X(b) if b < n else X(n - 1))
        step += [f"{x0:.1f},{Y(mean):.1f}", f"{x1:.1f},{Y(mean):.1f}"]
    if step:
        parts.append(f'<polyline points="{" ".join(step)}" fill="none" '
                     f'stroke="var(--accent)" stroke-width="3" stroke-linejoin="round" '
                     f'stroke-linecap="round"/>')
        for (a, b, mean, churn) in eras:
            xm = (X(a) + (X(b) if b < n else X(n - 1))) / 2
            parts.append(f'<text x="{xm:.1f}" y="{Y(mean)-9:.1f}" text-anchor="middle" '
                         f'font-size="12.5" font-weight="700" fill="var(--accent)">'
                         f'{mean:.0f}</text>')
            if churn is not None:
                parts.append(f'<text x="{xm:.1f}" y="{Y(mean)+15:.1f}" '
                             f'text-anchor="middle" font-size="10.5" font-weight="600" '
                             f'fill="var(--down)">{churn}% churned</text>')

    # thin x-labels to ~8 so a daily axis does not collide
    lstep = max(1, round(n / 8))
    for i, r in enumerate(tl):
        if i % lstep == 0 or i == n - 1:
            parts.append(f'<text x="{X(i):.1f}" y="{mt+ph+16:.0f}" text-anchor="middle" '
                         f'font-size="10" fill="var(--muted)">{esc(r["week"])}</text>')
    parts.append("</svg>")

    legend = ""
    if flags:
        items = "".join(f'<li><span class="flag">{k}</span> {esc(r["week"])}: '
                        f'{esc("; ".join(r["changes"]))}</li>' for k, r in flags)
        legend = f'<ol>{items}</ol>'
    detail = (f'{_lever_html(report)}'
              f'<h2>Efficiency over time</h2>'
              f'<p>The bold line is your average surviving work per Mtok for each '
              f'configuration era; the faint line is the daily actuals it averages. A '
              f'numbered flag marks a real setup change, dated to the day, so the level '
              f'between two flags is what that arrangement was worth.</p>'
              f'<p>Read the level with the <b>churn</b> under it: efficiency counts the '
              f'code that survived per token, and is blind to code the model wrote and '
              f'then deleted in the same session. A high level bought at high churn is a '
              f'lot of motion for the yield, so a cheaper-looking era can be the one that '
              f'was worse to work in. Efficiency is not quality.</p>'
              f'{"".join(parts)}{legend}'
              f'{render_small_multiples(report)}{render_attribution(report)}')
    body = f'<div class="vibrant">{hero}{detail}</div>'
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
    ("model", "by_model", "by model"),
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
    return (f'<h2>Fuel and work over time (by {esc(gran)})</h2>'
            f'<p>The three token streams that make up your fuel, against the code '
            f'that survived, each on its own scale. Slice by any dimension: '
            f'<select id="fw-sel">{"".join(groups)}</select></p>'
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

    def table(title, first_col, d):
        rows = "".join(
            f"<tr><td>{esc(str(k))}</td><td>{v['surviving']:,}</td>"
            f"<td>{v['net_complexity']:,}</td><td>{v['commits']}</td></tr>"
            for k, v in d.items())
        return (f"<h2>{esc(title)}</h2><table><thead><tr><th>{esc(first_col)}</th>"
                f"<th>surviving lines</th><th>complexity</th><th>commits</th>"
                f"</tr></thead><tbody>{rows}</tbody></table>")

    parts = []
    if attr.get("by_model"):
        parts.append(table("Surviving work by model", "model", attr["by_model"]))
    if attr.get("by_effort"):
        parts.append(table("Surviving work by effort", "effort", attr["by_effort"]))
    note = (f'<p style="margin-top:8px">Joined {attr["matched"]} commit(s) to a '
            f'session; {attr.get("unmatched", 0)} matched no session window.</p>')
    return "".join(parts) + note if parts else ""


def _page(inner):
    return ("<!doctype html><html><head><meta charset=utf-8>"
            "<meta name=viewport content=\"width=device-width,initial-scale=1\">"
            "<title>Vibrant: your efficiency over time</title></head>"
            f"<body>{inner}</body></html>\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--harness", default="claude-code")
    ap.add_argument("--repos", default="")
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
    args = ap.parse_args()

    repos = [os.path.expanduser(r) for r in args.repos.split(",") if r]
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
                          if args.labels else None)
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
