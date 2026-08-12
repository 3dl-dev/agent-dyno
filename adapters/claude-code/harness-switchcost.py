#!/usr/bin/env python3
"""
harness-switchcost.py, C6: the mid-session model-switch penalty.

Literature (Alderson / arXiv 2608.03893): switching the main-thread model
family mid-conversation repays prefill from a cold cache, the turn after a
switch cannot reuse the prior model's KV cache and re-reads history at low
cache-hit rate. This is the *pure* cross-family tax, distinct from C11's
delegation form (where each subagent is its own cached context).

Test: within a session, order turns by time; find turns where the base model
changed from the previous turn; compare that turn's cache-read share (cache_r /
all input) against the session's baseline (turns with no recent switch). A cold
re-read shows up as a cache-read-share collapse and elevated fresh-input.

Usage: python3 harness-switchcost.py model-behavior/snapshots/<dir>/mb-*.filtered.jsonl
Stdlib only.
"""
import json
import sys
from collections import defaultdict


def base(m):
    return (m or "").split("[")[0]


def cache_share(t):
    cr = t.get("cache_r_tok", 0)
    denom = cr + t.get("in_tok", 0) + t.get("cache_w_tok", 0)
    return (cr / denom) if denom else None


def main(paths):
    by_sess = defaultdict(list)
    for p in paths:
        for line in open(p):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("k") == "turn" and r.get("model") and base(r["model"]) != "<synthetic>":
                by_sess[r["sess"]].append(r)

    switch_sessions = 0
    post_switch = []      # cache-read share on the turn right after a switch
    baseline = []         # cache-read share on non-adjacent-to-switch turns
    post_freshtok = []    # fresh-input (in+cache_w) tokens on post-switch turns
    base_freshtok = []
    switch_pairs = defaultdict(int)  # (from_base, to_base) -> count

    for sid, turns in by_sess.items():
        turns = sorted([t for t in turns if t.get("ts")], key=lambda t: t["ts"])
        models = [base(t["model"]) for t in turns]
        switched_here = [False] * len(turns)
        any_switch = False
        for i in range(1, len(turns)):
            if models[i] != models[i - 1]:
                switched_here[i] = True
                any_switch = True
                switch_pairs[(models[i - 1], models[i])] += 1
        if any_switch:
            switch_sessions += 1
        for i, t in enumerate(turns):
            cs = cache_share(t)
            if cs is None:
                continue
            fresh = t.get("in_tok", 0) + t.get("cache_w_tok", 0)
            if switched_here[i]:
                post_switch.append(cs)
                post_freshtok.append(fresh)
            elif not (i + 1 < len(turns) and switched_here[i + 1]):
                # a steady-state turn (not the one before a switch either)
                baseline.append(cs)
                base_freshtok.append(fresh)

    def mean(x):
        return sum(x) / len(x) if x else 0.0

    print("=" * 70)
    print("C6  MID-SESSION MODEL-SWITCH PENALTY")
    print(f"  sessions with a mid-session model switch: {switch_sessions}/{len(by_sess)}")
    print(f"  switch events measured: {len(post_switch)}")
    if not post_switch:
        print("\n  No mid-session switches in this window, claim untestable here.")
        return
    print(f"\n  {'':22}{'cache-read share':>18}{'fresh-input tok/turn':>22}")
    print(f"  {'turn after a switch':22}{100*mean(post_switch):>17.1f}%{mean(post_freshtok):>22,.0f}")
    print(f"  {'steady-state turn':22}{100*mean(baseline):>17.1f}%{mean(base_freshtok):>22,.0f}")
    drop = 100 * (mean(baseline) - mean(post_switch))
    print(f"\n  cache-read share drop on the switch turn: {drop:+.1f} pts")
    print("  (a large negative drop + higher fresh-input = the cold-prefill tax)")
    print("\n  top switch transitions (from -> to, base model):")
    for (a, b), n in sorted(switch_pairs.items(), key=lambda kv: -kv[1])[:8]:
        a = a.replace("claude-", "")
        b = b.replace("claude-", "")
        print(f"    {a:14} -> {b:14} {n}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        sys.exit(1)
    main(args)
