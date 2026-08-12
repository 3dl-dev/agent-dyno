#!/usr/bin/env python3
"""
harness-subagenttax.py, C4: the per-subagent startup tax.

Literature ("The Subagent Tax"): every fan-out subagent re-reads the system
prompt / tool schemas / task brief from a cold cache before it does anything
useful, a fixed overhead paid once per subagent, so wide fan-out multiplies it.

Measured here directly from subagent transcripts: for each subagent, the input
machinery on its FIRST assistant message (cache_creation + cache_read + fresh
input = the cold prefill it loads before acting) and the tokens it spends before
its first productive edit. Attributed to the subagent's own model, because the
claim is that a cheap worker pays this tax too, sometimes more (no warm cache
to inherit).

Usage: python3 harness-subagenttax.py [--root ~/.claude/projects]
Stdlib only; prices via mb_cost.
"""
import glob
import json
import os
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
try:
    from mb_cost import price_tokens
except Exception:
    price_tokens = None

ROOT = os.path.expanduser("~/.claude/projects")
EDIT = ("Edit", "Write", "NotebookEdit")


def base(m):
    return (m or "").split("[")[0].replace("claude-", "")


def blocks(msg):
    c = (msg or {}).get("content")
    return c if isinstance(c, list) else []


def scan_subagent(path):
    """Return (model, prefill_tokens, startup_tokens, reached_edit)."""
    model = None
    prefill = None
    startup = 0
    reached = False
    for line in open(path, errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") != "assistant":
            continue
        m = d.get("message") or {}
        mm = m.get("model")
        if not mm or mm == "<synthetic>":
            continue
        model = model or base(mm)
        u = m.get("usage") or {}
        toks = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                + u.get("cache_read_input_tokens", 0))
        if prefill is None:
            prefill = toks  # first assistant message = the cold load
        if not reached:
            startup += u.get("output_tokens", 0)
            for b in blocks(m):
                if b.get("type") == "tool_use" and b.get("name") in EDIT:
                    reached = True
                    break
    return model, (prefill or 0), startup, reached


def main(root):
    subs = glob.glob(os.path.join(root, "*", "*", "subagents", "**", "*.jsonl"),
                     recursive=True)
    agg = defaultdict(lambda: defaultdict(float))
    n = defaultdict(int)
    for p in subs:
        model, prefill, startup, reached = scan_subagent(p)
        if not model or not prefill:
            continue
        a = agg[model]
        n[model] += 1
        a["prefill"] += prefill
        a["startup_out"] += startup
        a["reached"] += 1 if reached else 0

    print(f"scanned {sum(n.values())} subagents\n")
    hdr = (f"{'worker model':16}{'subs':>6}{'prefill tok (mean)':>20}"
           f"{'reached edit%':>15}{'$ prefill (mean)':>18}")
    print(hdr)
    print("-" * len(hdr))
    for m in sorted(n, key=lambda x: -n[x]):
        a = agg[m]
        pref = a["prefill"] / n[m]
        dollar = price_tokens(f"claude-{m}", {"cache_r": pref}) if price_tokens else 0
        print(f"{m:16}{n[m]:>6}{pref:>20,.0f}{100*a['reached']/n[m]:>14.0f}%"
              f"{dollar:>18.4f}")
    print("\nprefill = input machinery on the subagent's first assistant message, ")
    print("the cold load paid once per subagent, before any productive work.")
    print("A wide wave pays this N times; a cheap worker still pays it.")


if __name__ == "__main__":
    root = ROOT
    if "--root" in sys.argv:
        root = os.path.expanduser(sys.argv[sys.argv.index("--root") + 1])
    main(root)
