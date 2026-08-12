#!/usr/bin/env python3
"""
harness-fingerprint.py, granular engine taxonomy + the O(read) test.
Extends the coarse solo/delegate/workflow of harness-characterize.py into
named SETUPS, using signal that separates a naive plain-Claude session from a
practice-kit swarm from a parallel-session driver:

  - skill signature   (which skills were invoked; swarm-*/cost-discipline/... = kit)
  - dispatch mode     (Workflow vs plain Agent vs none)
  - coordination      (SendMessage intensity = live multi-agent / parallel driver)
  - model routing     (homogeneous vs cross-family)

Plus the O(read) economics that the "just use Opus" research turns on: a worker
in a different model family cannot reuse the orchestrator's KV/prompt cache, so
it starts cold and pays full read cost. Measured here as worker cache-read share
and reads-per-edit, split by homogeneous vs cross-model routing.

Usage:
  python3 harness-fingerprint.py <snapshot-dir>/*.jsonl
Stdlib only.
"""
import glob
import json
import os
import sys
from collections import defaultdict, Counter

ROOT = os.path.expanduser("~/.claude/projects")
KIT_SKILLS = {"swarm-plan", "swarm-dispatch", "cost-discipline", "adversarial-design",
              "escalation-design", "delegate", "sweep", "revgen-design", "pitch-prep"}


def base(m):
    return (m or "").split("[")[0].replace("claude-", "")


def session_skills():
    """sess_id -> Counter(skill_name) from raw transcripts (main + subagents)."""
    out = defaultdict(Counter)
    for mp in glob.glob(os.path.join(ROOT, "*", "*.jsonl")):
        sid = os.path.basename(mp)[:-6]
        try:
            fh = open(mp)
        except Exception:
            continue
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            m = d.get("message") or {}
            c = m.get("content")
            if not isinstance(c, list):
                continue
            for b in c:
                if b.get("type") == "tool_use" and b.get("name") == "Skill":
                    nm = (b.get("input") or {}).get("skill") or (b.get("input") or {}).get("name")
                    if nm:
                        out[sid][nm] += 1
    return out


def classify(s, tc, skills):
    """Assign a granular setup label by priority."""
    wf = (s.get("workflows") or 0) + (s.get("wf_agents") or 0)
    pa = s.get("plain_agents") or 0
    sends = tc.get("SendMessage", 0)
    kit = sum(v for k, v in skills.items() if k in KIT_SKILLS)
    turns = max(1, tc.get("_turns", 1))
    has_sub = wf > 0 or pa > 0
    if sends / turns >= 1.0 and has_sub:
        return "parallel-driver"          # live multi-agent coordination
    if wf > 0:
        return "swarm-workflow" if kit else "workflow"
    if pa > 0:
        return "swarm-delegate" if kit else "plain-delegate"
    if skills:
        return "skilled-solo"
    return "naive-solo"


def main(paths):
    sessions, code, tc = {}, {}, defaultdict(Counter)
    for p in paths:
        for line in open(p):
            try:
                r = json.loads(line)
            except Exception:
                continue
            k = r.get("k")
            if k == "session":
                sessions[r["sess"]] = r
            elif k == "code":
                code[r["sess"]] = r
            elif k == "turn":
                tc[r["sess"]]["_turns"] += 1
                for t, c in (r.get("tc") or {}).items():
                    tc[r["sess"]][t] += c

    sys.stderr.write("scanning transcripts for skill signatures ...\n")
    skills = session_skills()

    # ── classify + aggregate reads/cache economics ──
    setup_of = {}
    agg = defaultdict(lambda: defaultdict(float))
    n = Counter()
    for sid, s in sessions.items():
        lab = classify(s, tc[sid], skills.get(sid, Counter()))
        setup_of[sid] = lab
        n[lab] += 1
        c = code.get(sid) or {}
        o, w = c.get("orch") or {}, c.get("work") or {}
        a = agg[lab]
        for half in (o, w):
            a["edits"] += half.get("edits", 0)
            a["reads"] += half.get("reads", 0)
        a["w_cache_r"] += w.get("cache_r_tok", 0)
        a["w_in"] += w.get("in_tok", 0)
        a["w_cache_w"] += w.get("cache_w_tok", 0)
        a["o_cache_r"] += o.get("cache_r_tok", 0)
        a["o_in"] += o.get("in_tok", 0)
        a["o_cache_w"] += o.get("cache_w_tok", 0)

    print("=" * 88)
    print("GRANULAR SETUPS  (sessions, tool signature, read economics)")
    hdr = f"{'setup':18}{'sess':>5}{'reads/edit':>12}{'orch cacheR%':>14}{'worker cacheR%':>16}"
    print(hdr); print("-" * len(hdr))
    order = ["naive-solo", "skilled-solo", "plain-delegate", "swarm-delegate",
             "workflow", "swarm-workflow", "parallel-driver"]
    for lab in order:
        if lab not in n:
            continue
        a = agg[lab]
        rpe = a["reads"] / max(1, a["edits"])
        ocr = 100 * a["o_cache_r"] / max(1, a["o_cache_r"] + a["o_in"] + a["o_cache_w"])
        wcr = 100 * a["w_cache_r"] / max(1, a["w_cache_r"] + a["w_in"] + a["w_cache_w"])
        wcr_s = f"{wcr:>15.1f}" if (a["w_cache_r"] + a["w_in"]) else f"{'-':>15}"
        print(f"{lab:18}{n[lab]:>5}{rpe:>12.1f}{ocr:>13.1f}%{wcr_s}%")

    # ── the O(read) test: worker cold-cache tax, homogeneous vs cross-model ──
    print("\n" + "=" * 88)
    print("O(read) TEST  (delegating sessions: does a cross-family worker start cold?)")
    rt = defaultdict(lambda: defaultdict(float))
    rn = Counter()
    for sid, s in sessions.items():
        if setup_of[sid] in ("naive-solo", "skilled-solo"):
            continue
        mix = s.get("submix") or {}
        if not mix:
            continue
        wb = {base(m) for m in mix}
        ob = base(s.get("model"))
        route = "homogeneous" if wb == {ob} else "cross-family"
        c = code.get(sid) or {}
        w = c.get("work") or {}
        a = rt[route]
        rn[route] += 1
        a["w_cache_r"] += w.get("cache_r_tok", 0)
        a["w_in"] += w.get("in_tok", 0)
        a["w_cache_w"] += w.get("cache_w_tok", 0)
        a["reads"] += w.get("reads", 0)
        a["edits"] += w.get("edits", 0)
    hdr2 = f"{'worker routing':16}{'sess':>5}{'worker cacheR%':>16}{'worker reads/edit':>19}"
    print(hdr2); print("-" * len(hdr2))
    for route in ("homogeneous", "cross-family"):
        if route not in rn:
            continue
        a = rt[route]
        wcr = 100 * a["w_cache_r"] / max(1, a["w_cache_r"] + a["w_in"] + a["w_cache_w"])
        rpe = a["reads"] / max(1, a["edits"])
        print(f"{route:16}{rn[route]:>5}{wcr:>15.1f}%{rpe:>19.1f}")
    print("\nHypothesis (O(read) / 'just use Opus'): a cross-family worker cannot reuse the")
    print("orchestrator's cache, so it shows LOWER cache-read share and/or MORE reads/edit.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__); sys.exit(1)
    main(args)
