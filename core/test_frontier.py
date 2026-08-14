#!/usr/bin/env python3
"""
Acceptance test for frontier.py (the federation engine), the spec made executable.

Builds a fixture frontier with entries across two shapes (plus a duplicate id and an
out-of-range entry) and asserts validate / merge / summarize and byte-identical
re-runs. Regenerate frontier.py from frontier.spec.md and this test must still pass.

    python3 core/test_frontier.py     # exits 0 on pass, 1 on fail
Stdlib only.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import frontier  # noqa: E402


def entry(eid, engine, effort, orch, worker, regime, vec, samples,
          harness="claude-code", horizon="session", technique="secret sauce X"):
    return {"id": eid, "harness": harness, "engine": engine, "effort": effort,
            "model_roles": {"orchestrator": orch, "worker": worker},
            "review_regime": regime, "horizon": horizon, "samples": samples,
            "technique": technique, "lever": "do the thing",
            "vector": vec, "date": "2026-08-01", "proof": "tier-1-self-report"}


def A(eid, spm, waste, crd, dps, samples):
    # shape A: solo / high / strong / no-worker / spec+acceptance / session
    return entry(eid, "solo", "high", "strong", None, "spec + acceptance",
                 {"survkb_per_outmtok": spm, "waste_pct": waste,
                  "cache_read_pct": crd, "dollars_per_survkb": dps}, samples)


def B(eid, spm, waste, crd, dps, samples):
    # shape B: delegate / high / strong / cheap / agentic / session
    return entry(eid, "delegate", "high", "strong", "cheap", "agentic review pass",
                 {"survkb_per_outmtok": spm, "waste_pct": waste,
                  "cache_read_pct": crd, "dollars_per_survkb": dps}, samples)


def fr(entries):
    return {"schema": "agent-dyno/frontier@2", "note": "fixture", "axes": {},
            "entries": entries}


def main():
    fails = []

    # ---- (1) validate ----
    clean = fr([A("p1", 100, 10, 90, 1.0, 10)])
    if frontier.validate(clean):
        fails.append(f"validate flagged a clean frontier: {frontier.validate(clean)}")
    bad = fr([A("p1", 100, 10, 90, 1.0, 10),
              A("bad", 100, 150, 90, 1.0, 5)])  # waste_pct 150 out of range
    issues = frontier.validate(bad)
    if not any("bad" in i and "waste" in i for i in issues):
        fails.append(f"validate did not flag out-of-range waste_pct: {issues}")
    if not any("samples" in i for i in frontier.validate(
            fr([A("z", 100, 10, 90, 1.0, 0)]))):  # samples must be positive
        fails.append("validate did not flag non-positive samples")

    # ---- (2) merge: fold children, skip duplicate ids, idempotent ----
    parent = fr([A("p1", 100, 10, 90, 1.0, 10)])
    childA = fr([A("c1", 200, 20, 92, 2.0, 5), A("c2", 300, 30, 94, 3.0, 5),
                 A("p1", 999, 99, 99, 9.0, 1)])  # duplicate id -> skipped
    childB = fr([B("c3", 150, 25, 96, 1.3, 8)])
    merged = frontier.merge(parent, [childA, childB])
    ids = [e["id"] for e in merged["entries"]]
    if ids != ["p1", "c1", "c2", "c3"]:
        fails.append(f"merge order/dedup wrong: {ids}")
    # the surviving p1 is the parent's (not the child's 999 vector)
    p1 = next(e for e in merged["entries"] if e["id"] == "p1")
    if p1["vector"]["survkb_per_outmtok"] != 100:
        fails.append("merge let a duplicate child id overwrite the parent entry")
    # idempotent: merging the already-merged result with the same children is a no-op
    twice = frontier.merge(merged, [childA, childB])
    if [e["id"] for e in twice["entries"]] != ids:
        fails.append("merge is not idempotent")
    # schema/axes preserved
    if merged["schema"] != "agent-dyno/frontier@2":
        fails.append("merge dropped the schema")

    # ---- (3) summarize: one entry per shape, median vector, summed samples ----
    src = [A("p1", 100, 10, 90, 1.0, 10), A("c1", 200, 20, 92, 2.0, 5),
           A("c2", 300, 30, 94, 3.0, 5), B("c3", 150, 25, 96, 1.3, 8)]
    summ = frontier.summarize(src, date="2026-08-14")
    byshape = {(e["engine"], e["effort"]): e for e in summ}
    if len(summ) != 2:
        fails.append(f"summarize should yield 2 shape summaries, got {len(summ)}")
    sa = byshape.get(("solo", "high"))
    if not sa:
        fails.append("summarize missing the solo/high shape")
    else:
        # medians of [100,200,300]=200, [10,20,30]=20, [90,92,94]=92, [1,2,3]=2
        v = sa["vector"]
        if v.get("survkb_per_outmtok") != 200 or v.get("waste_pct") != 20 \
                or v.get("cache_read_pct") != 92 or v.get("dollars_per_survkb") != 2:
            fails.append(f"summarize median vector wrong: {v}")
        if sa.get("samples") != 20 or sa.get("entries_summarized") != 3:
            fails.append(f"summarize counts wrong: samples={sa.get('samples')} "
                         f"entries={sa.get('entries_summarized')}")
        if sa.get("aggregate") is not True or sa.get("proof") != "tier-1-aggregate":
            fails.append("summarize did not mark the entry aggregate / tier-1-aggregate")
        if not str(sa.get("id", "")).startswith("summary-"):
            fails.append(f"summarize id is not a summary id: {sa.get('id')}")
        # anonymity: no source id, no per-entry technique prose leaked
        blob = json.dumps(sa)
        if "p1" in blob or "c1" in blob or "secret sauce" in blob:
            fails.append(f"summarize leaked a source id or technique prose: {sa}")

    # min-samples floor: shape B has 8 total; require 10 -> B omitted, A kept
    floored = frontier.summarize(src, date="2026-08-14", min_samples=10)
    shapes = {(e["engine"], e["effort"]) for e in floored}
    if ("delegate", "high") in shapes or ("solo", "high") not in shapes:
        fails.append(f"summarize --min-samples floor wrong: {sorted(shapes)}")

    # ---- (4) determinism ----
    if json.dumps(frontier.summarize(src, date="2026-08-14"), sort_keys=True) != \
       json.dumps(summ, sort_keys=True):
        fails.append("summarize is not deterministic across runs")
    if json.dumps(frontier.merge(parent, [childA, childB]), sort_keys=True) != \
       json.dumps(merged, sort_keys=True):
        fails.append("merge is not deterministic across runs")

    if fails:
        print("FAIL  frontier:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  frontier: validate, merge (dedup, idempotent), summarize, determinism")
    return 0


if __name__ == "__main__":
    sys.exit(main())
