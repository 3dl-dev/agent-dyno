#!/usr/bin/env python3
"""
harness-modeleffect.py, isolate the MODEL effect at fixed harness, and the
model x harness interaction. Answers "is model irrelevant?": no. Within one
engine, output-token -> surviving-code efficiency and waste vary by model; and
a model's waste depends on the harness wrapped around it (interaction).

Metric per (engine, model): waste% (killed/born), survKB per Mtok-output
(how expensive output tokens convert to surviving code), $/surv-KB, output
$-share. Output is priced per turn's model/date.

Usage: python3 harness-modeleffect.py <snapshot-dir>
Stdlib only; imports model-behavior-survival + mb_cost.
"""
import glob
import importlib
import json
import os
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
surv = importlib.import_module("model-behavior-survival")
from mb_cost import session_cost, price_tokens

MIN_N = 4


def b(m):
    return (m or "").split("[")[0].replace("claude-", "")


def engine(s):
    if (s.get("workflows") or 0) > 0 or (s.get("wf_agents") or 0) > 0:
        return "workflow"
    if (s.get("plain_agents") or 0) > 0:
        return "delegate"
    return "solo"


def _pick(snap, prefix):
    """Snapshot JSONL for `prefix` (mb/mc); accepts plain or legacy .filtered."""
    hits = sorted(glob.glob(os.path.join(snap, f"{prefix}-*.jsonl")))
    if not hits:
        sys.exit(f"no {prefix}-*.jsonl found in {snap}")
    return hits[0]


def main(snap):
    sessions, code = {}, {}
    for l in open(_pick(snap, "mb")):
        r = json.loads(l)
        if r.get("k") == "session":
            sessions[r["sess"]] = r
    for l in open(_pick(snap, "mc")):
        r = json.loads(l)
        if r.get("k") == "code":
            code[r["sess"]] = r

    sys.stderr.write("scanning transcripts for per-session survival ...\n")
    cache_path = os.path.join(snap, "survival-cache.json")
    sv = surv.per_session_survival(cache_path=cache_path, verbose=True)

    grid = defaultdict(lambda: defaultdict(float))
    N = defaultdict(int)
    for sid, s in sessions.items():
        if sid not in sv:
            continue
        eng, m = engine(s), b(s.get("model"))
        born, killed = sv[sid]
        c = code.get(sid) or {}
        o, w = c.get("orch") or {}, c.get("work") or {}
        out = o.get("out_tok", 0) + w.get("out_tok", 0)
        g = grid[(eng, m)]
        N[(eng, m)] += 1
        g["born"] += born
        g["killed"] += killed
        g["out"] += out
        g["dollars"] += session_cost(s)
        g["out_dollars"] += price_tokens(s.get("model"),
                                         {"out": out}, date=s.get("day"))

    for eng in ("solo", "delegate", "workflow"):
        rows = [(m, grid[(eng, m)]) for (e, m) in grid if e == eng and N[(eng, m)] >= MIN_N]
        if not rows:
            continue
        print(f"\n=== {eng.upper()} engine, by model (N>={MIN_N}) ===")
        print(f"{'model':11}{'sess':>5}{'waste%':>8}{'survKB/Mtok-out':>17}"
              f"{'$/surv-KB':>11}{'out$share':>10}")
        for m, g in sorted(rows, key=lambda kv: -N[(eng, kv[0])]):
            surv_kb = max(1e-9, (g["born"] - g["killed"]) / 1000)
            print(f"{m:11}{N[(eng, m)]:>5}{100*g['killed']/max(1, g['born']):>7.0f}%"
                  f"{surv_kb/max(1e-9, g['out']/1e6):>17.0f}{g['dollars']/surv_kb:>11.2f}"
                  f"{100*g['out_dollars']/max(1e-9, g['dollars']):>9.0f}%")

    # interaction: same model, waste across engines
    print("\n=== MODEL x HARNESS INTERACTION: waste% by model across engines ===")
    models = sorted({m for (e, m) in grid if N[(e, m)] >= MIN_N})
    print(f"{'model':11}" + "".join(f"{e:>12}" for e in ('solo', 'delegate', 'workflow')))
    for m in models:
        cells = ""
        for e in ('solo', 'delegate', 'workflow'):
            g = grid.get((e, m))
            if g and N[(e, m)] >= MIN_N:
                cells += f"{100*g['killed']/max(1, g['born']):>11.0f}%"
            else:
                cells += f"{'-':>12}"
        print(f"{m:11}{cells}")
    print("\nA model efficient solo can waste heavily once it orchestrates: "
          "efficiency is f(model, harness, interaction), not either alone.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        sys.exit(1)
    main(args[0])
