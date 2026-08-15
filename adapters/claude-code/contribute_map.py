#!/usr/bin/env python3
"""
contribute_map.py, the producer for the federated shared map (contribute_map.spec.md).

Turns an operator's own per-session metrics (the driver's --dump-sessions output)
into a shareable vibrant/som-contribution@1, disclosing no logs. It reads the
operator's per-session metric dicts and the published reference codebook
(vibrant/som-codebook@1), assigns each session to a cell on that SHARED frame via
som_train.bmu, and aggregates per-cell cost, surviving work, and count. Assigning
to the SHARED codebook, not the operator's own trained SOM, is the whole point:
every operator lands their sessions on the same lattice, so the per-cell grids
are comparable and add. No session, sid, repo, vec, or day leaves in the output;
som_merge.contribution packages only the allowed keys.

Usage:
  python3 contribute_map.py --sessions sessions.json --codebook reference-codebook.json
      --op <opaque-tag> [--window-days 14] [--now-day YYYY-MM-DD] [--out contribution.json]
  python3 contribute_map.py --selftest        # runs the acceptance fixture, exits 0/1
Stdlib only.
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "core"))

import session_features
import som_train
import som_merge

SCHEMA_IN = "vibrant/som-codebook@1"


def _lattice_ok(lattice):
    return (isinstance(lattice, dict)
            and isinstance(lattice.get("rows"), int) and lattice.get("rows") > 0
            and isinstance(lattice.get("cols"), int) and lattice.get("cols") > 0)


def build(sessions, codebook, op, window_days=14, now_day=None):
    """Pure, deterministic: (sessions, codebook, op, window_days, now_day) ->
    vibrant/som-contribution@1. Raises ValueError if the codebook's feature
    names do not match session_features.FEATURE_NAMES, or the lattice is
    missing/degenerate."""
    if codebook.get("names") != session_features.FEATURE_NAMES:
        raise ValueError("codebook names do not match session_features.FEATURE_NAMES")
    lattice = codebook.get("lattice")
    if not _lattice_ok(lattice):
        raise ValueError(f"codebook lattice missing or degenerate: {lattice!r}")

    kept = [m for m in sessions if m.get("day")]
    if now_day:
        anchor = now_day
    else:
        anchor = max((m["day"] for m in kept), default=None)
    if anchor is not None:
        anchor_date = datetime.date.fromisoformat(anchor)
        cutoff_date = anchor_date - datetime.timedelta(days=window_days)
        cutoff = cutoff_date.isoformat()
        kept = [m for m in kept if m["day"] >= cutoff]

    rows, cols = lattice["rows"], lattice["cols"]
    cost = [[0.0] * cols for _ in range(rows)]
    surv = [[0.0] * cols for _ in range(rows)]
    support = [[0] * cols for _ in range(rows)]

    for m in kept:
        vec = session_features.features(m)
        r, c = som_train.bmu(codebook["codebook"], vec)
        cost[r][c] += m["dollars"]
        surv[r][c] += max(m["born"] - m["killed"], 0) / 1024
        support[r][c] += 1

    out_cost = [[None] * cols for _ in range(rows)]
    out_surv = [[None] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            if support[r][c] > 0:
                out_cost[r][c] = round(cost[r][c], 6)
                out_surv[r][c] = round(surv[r][c], 6)

    return som_merge.contribution(out_cost, out_surv, support,
                                   codebook["version"], lattice, op)


def selftest():
    import test_contribute_map as t
    return t.main()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", help="JSON array of per-session metric dicts")
    ap.add_argument("--codebook", help="vibrant/som-codebook@1 JSON")
    ap.add_argument("--op", help="opaque operator tag")
    ap.add_argument("--window-days", type=int, default=14, help="recency window in days")
    ap.add_argument("--now-day", default=None, help="anchor day YYYY-MM-DD (default: max session day)")
    ap.add_argument("--out", default=None, help="write contribution JSON here (else stdout)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.sessions or not args.codebook or not args.op:
        ap.error("--sessions, --codebook, and --op are required (or use --selftest)")
    with open(args.sessions) as f:
        sessions = json.load(f)
    with open(args.codebook) as f:
        codebook = json.load(f)
    out = build(sessions, codebook, args.op, window_days=args.window_days,
                now_day=args.now_day)
    text = json.dumps(out, indent=2, sort_keys=True) + "\n"
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"contribution written: {args.out} (op={out['op']})")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
