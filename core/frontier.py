#!/usr/bin/env python3
# REFERENCE BUILD. Source of truth: frontier.spec.md (what it must do)
# + test_frontier.py (the verification). Code is a regenerable artifact:
# rebuild it from the spec and the acceptance test must still pass. See SOURCE.md.
"""
frontier.py, the federation engine.

Makes a frontier a *federated* commons instead of a single hand-edited file. Three
deterministic operations, no network and no policy:

  validate   tier-0 sanity: the floor every entry must pass.
  merge      fold child frontiers into a parent, deduplicated: a team's local
             roll-up, an operation the owner runs, never an automatic push.
  summarize  turn a frontier into one anonymized aggregate entry per shape: what an
             enterprise shares upward without handing over individual runs.

A frontier is `{schema, note, axes, entries[]}` (agent-dyno/frontier@2). Stdlib
only, harness-neutral, deterministic: output is a pure function of the inputs (and,
for summarize, a caller-supplied date; the library never reads a clock).

Usage:
  frontier.py validate <frontier.json>
  frontier.py merge --into <parent.json> <child.json> [...] [--out <path>]
  frontier.py summarize <frontier.json> [--date YYYY-MM-DD] [--min-samples N] [--out <path>]
"""
import argparse
import datetime
import hashlib
import json
import math
import os
import sys

SCHEMA = "agent-dyno/frontier@2"
_PCT_AXES = ("waste_pct", "cache_read_pct")


def new_frontier(note=""):
    """An empty, valid frontier skeleton. The whole of a new board: a file, no
    server."""
    return {"schema": SCHEMA, "note": note, "axes": {}, "entries": []}


def _num_ok(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) \
        and math.isfinite(v)


def validate(frontier):
    """Tier-0 sanity issues, sorted, empty if clean. The same floor dyno-contribute
    applies, reused so a merged or summarized frontier is checkable in one call."""
    issues = []
    for e in frontier.get("entries", []):
        eid = e.get("id", "<no-id>")
        for req in ("engine", "vector", "date"):
            if req not in e:
                issues.append(f"{eid}: missing required key '{req}'")
        vec = e.get("vector") or {}
        for axis, val in vec.items():
            if not _num_ok(val):
                issues.append(f"{eid}: vector.{axis} is not a finite number ({val!r})")
            elif val < 0:
                issues.append(f"{eid}: vector.{axis} is negative ({val})")
            elif axis in _PCT_AXES and not (0 <= val <= 100):
                issues.append(f"{eid}: vector.{axis} out of range [0,100] ({val})")
        s = e.get("samples")
        if s is not None and (not isinstance(s, int) or isinstance(s, bool) or s <= 0):
            issues.append(f"{eid}: samples must be a positive integer ({s!r})")
    return sorted(issues)


def merge(parent, children):
    """Fold each child's entries into the parent's, deduplicated by id (first id
    wins, so a parent's curated entry is never overwritten and re-running is
    idempotent). schema / note / axes are the parent's; only entries grows."""
    out = dict(parent)
    entries = list(parent.get("entries", []))
    seen = {e.get("id") for e in entries}
    for child in children:
        for e in child.get("entries", []):
            if e.get("id") in seen:
                continue
            seen.add(e.get("id"))
            entries.append(e)
    out["entries"] = entries
    return out


def _shape(e):
    """The tuple that defines a rig shape on the board. Entries sharing it roll into
    one summary."""
    roles = e.get("model_roles") or {}
    return (e.get("harness"), e.get("engine"), e.get("effort"),
            roles.get("orchestrator"), roles.get("worker"),
            e.get("review_regime"), e.get("horizon"))


def _median(vals):
    s = sorted(vals)
    n = len(s)
    m = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    m = round(m, 4)
    return int(m) if m == int(m) else m


def summarize(entries, date, min_samples=1):
    """One anonymized aggregate entry per shape. Carries shape + median vector +
    counts, and nothing that identifies a run or a person (no source id, no
    technique prose). This is the roll-up an org chooses to share upward."""
    groups = {}
    for e in entries:
        groups.setdefault(_shape(e), []).append(e)
    out = []
    for shape, es in groups.items():
        harness, engine, effort, orch, worker, regime, horizon = shape
        total_samples = sum(int(e.get("samples") or 0) for e in es)
        if total_samples < min_samples:
            continue
        axes = sorted({a for e in es for a in (e.get("vector") or {})})
        vector = {}
        for a in axes:
            vals = [(e.get("vector") or {}).get(a) for e in es]
            vals = [v for v in vals if _num_ok(v)]
            if vals:
                vector[a] = _median(vals)
        h = hashlib.sha256(repr(shape).encode()).hexdigest()[:8]
        out.append({
            "id": f"summary-{engine}-{effort}-{h}",
            "harness": harness, "engine": engine, "effort": effort,
            "model_roles": {"orchestrator": orch, "worker": worker},
            "review_regime": regime, "horizon": horizon,
            "samples": total_samples, "entries_summarized": len(es),
            "vector": vector, "aggregate": True,
            "technique": f"Aggregate of {len(es)} {engine} setups at {effort} effort.",
            "date": date, "proof": "tier-1-aggregate",
        })
    return sorted(out, key=lambda e: e["id"])


def _load(path):
    with open(path) as f:
        return json.load(f)


def _emit(obj, out_path):
    text = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    if out_path:
        with open(out_path, "w") as f:
            f.write(text)
        print(f"wrote {out_path}", file=sys.stderr)
    else:
        sys.stdout.write(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description="frontier federation engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("path"); i.add_argument("--note", default="")
    i.add_argument("--force", action="store_true")
    v = sub.add_parser("validate"); v.add_argument("frontier")
    m = sub.add_parser("merge")
    m.add_argument("--into", required=True); m.add_argument("children", nargs="+")
    m.add_argument("--out", default=None)
    s = sub.add_parser("summarize")
    s.add_argument("frontier")
    s.add_argument("--date", default=None)
    s.add_argument("--min-samples", type=int, default=1)
    s.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    if args.cmd == "init":
        if os.path.exists(args.path) and not args.force:
            print(f"refusing to overwrite {args.path} (use --force)")
            return 1
        with open(args.path, "w") as f:
            json.dump(new_frontier(args.note), f, indent=2)
            f.write("\n")
        ap_path = os.path.abspath(args.path)
        print(f"created your frontier: {args.path}")
        print("that is the whole setup, no server. two steps to use it:")
        print(f"  1. make it your default:  export DYNO_FRONTIER={ap_path}")
        print("  2. view it: open leaderboard/dyno.html and point it at this file")
        print("now dyno-report compares against it and contributions land here by "
              "default; share upward only when you choose (merge / summarize).")
        return 0
    if args.cmd == "validate":
        issues = validate(_load(args.frontier))
        if issues:
            print(f"{len(issues)} issue(s):")
            for i in issues:
                print("  -", i)
            return 1
        print("clean: every entry passes tier-0 sanity")
        return 0
    if args.cmd == "merge":
        merged = merge(_load(args.into), [_load(c) for c in args.children])
        _emit(merged, args.out)
        for i in validate(merged):
            print("  ! " + i, file=sys.stderr)
        return 0
    if args.cmd == "summarize":
        # the CLI may read the clock once for convenience; the library never does.
        date = args.date or datetime.date.today().isoformat()
        src = _load(args.frontier)
        summaries = summarize(src.get("entries", []), date, args.min_samples)
        _emit({"schema": src.get("schema", SCHEMA), "note": "", "axes": {},
               "entries": summaries}, args.out)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
