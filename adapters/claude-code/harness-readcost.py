#!/usr/bin/env python3
"""
harness-readcost.py, adjudicate the O(reads) claims against our own logs.

Tests two literature claims:
  C1  "cost is O(reads)"     , read machinery (input + cache-read + cache-write)
                                   dominates $ vs generation (output).
  C2  "reads grow with depth", per-turn read cost rises as the conversation
                                   gets longer (the quadratic-ish curve).

Reads $ = price(input + cache_read + cache_write); Gen $ = price(output), per turn
at the turn's model + date. Depth = cumulative tokens seen in the session so far.

Usage: python3 harness-readcost.py <snapshot-dir>/mb-*.jsonl
Stdlib only; imports mb_cost.
"""
import json
import os
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from mb_cost import price_tokens


def read_gen_cost(t):
    """(read_dollars, gen_dollars) for one turn record."""
    m, day = t.get("model"), (t.get("ts") or "")[:10] or None
    read = price_tokens(m, {"in": t.get("in_tok", 0), "cache_r": t.get("cache_r_tok", 0),
                            "cache_w": t.get("cache_w_tok", 0), "out": 0}, date=day)
    gen = price_tokens(m, {"in": 0, "cache_r": 0, "cache_w": 0,
                           "out": t.get("out_tok", 0)}, date=day)
    return read, gen


def main(paths):
    by_sess = defaultdict(list)
    for p in paths:
        for line in open(p):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("k") == "turn":
                by_sess[r["sess"]].append(r)

    tot_read = tot_gen = 0.0
    depth_bins = defaultdict(lambda: [0.0, 0.0, 0])  # bin -> [read$, gen$, nturns]
    BINS = [0, 25_000, 50_000, 100_000, 200_000, 400_000, 10**12]
    BIN_LABEL = ["<25k", "25-50k", "50-100k", "100-200k", "200-400k", ">400k"]

    for sid, turns in by_sess.items():
        turns = sorted([t for t in turns if t.get("ts")], key=lambda t: t["ts"])
        cum_tok = 0
        for t in turns:
            rd, gn = read_gen_cost(t)
            tot_read += rd
            tot_gen += gn
            # depth = context size proxy = cache_read tokens on this turn (the
            # live context being re-read), fall back to cumulative.
            ctx = t.get("cache_r_tok", 0) or cum_tok
            b = next(i for i in range(len(BINS) - 1) if BINS[i] <= ctx < BINS[i + 1])
            depth_bins[b][0] += rd
            depth_bins[b][1] += gn
            depth_bins[b][2] += 1
            cum_tok += t.get("in_tok", 0) + t.get("out_tok", 0) + t.get("cache_w_tok", 0)

    total = tot_read + tot_gen
    print("=" * 70)
    print("C1  IS COST O(READS)?   read $ = input+cache_read+cache_write")
    print(f"  read machinery : ${tot_read:>10,.0f}   {100*tot_read/max(1e-9,total):>5.1f}% of $")
    print(f"  generation     : ${tot_gen:>10,.0f}   {100*tot_gen/max(1e-9,total):>5.1f}% of $")
    print(f"  => reads are {tot_read/max(1e-9,tot_gen):.1f}x generation cost")

    print("\n" + "=" * 70)
    print("C2  DO READS GROW WITH DEPTH?   per-turn read $ by live-context size")
    print(f"  {'context (cache-read tok)':26}{'turns':>7}{'read$/turn':>12}{'read share':>12}")
    for b, lbl in enumerate(BIN_LABEL):
        rd, gn, nt = depth_bins[b]
        if nt == 0:
            continue
        share = 100 * rd / max(1e-9, rd + gn)
        print(f"  {lbl:26}{nt:>7}{rd/nt:>12.3f}{share:>11.1f}%")
    print("\n  read$/turn rising down the column = reads scale with conversation depth.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__); sys.exit(1)
    main(args)
