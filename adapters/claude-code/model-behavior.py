#!/usr/bin/env python3
"""
Model-behavior extractor, per-turn and per-session orchestration/style metrics,
attributed to the assistant model that produced them.

Emits compact JSONL (no raw transcript text) so it can be run on remote machines
and the output shipped back for merged analysis:

    python3 model-behavior.py --out ~/model-behavior-$(hostname).jsonl

Two record kinds:
  {"k":"turn",    ...}   one per human->assistant turn on the main thread
  {"k":"session", ...}   one per session, with subagent fan-out census

Analyze merged output with model-behavior-report.py.
"""
import argparse
import glob
import json
import os
import re
import socket
import statistics as st
from collections import Counter

DISPATCH = {"Agent", "Workflow", "Task"}
TRACK_TOOLS = ["Agent", "Workflow", "Task", "Skill", "SendMessage",
               "AskUserQuestion", "ExitPlanMode", "Bash", "Read", "Edit", "Write"]

NUDGE = re.compile(
    r"^\s*(continue|keep going|go on|proceed|go ahead|carry on|yes|y|yep|do it|"
    r"please continue|finish|finish it|keep working|don'?t stop|why did you stop|"
    r"resume|next|more|ok|okay|sure|go)\s*[.!]?\s*$", re.I)

LEX = {
    "caveat": r"\b(caveat|worth flagging|i should flag|one concern|to be clear|"
              r"for transparency|note that|heads[- ]up|strictly speaking|subtle(ty)?)\b",
    "hedge": r"\b(likely|probably|appears to|seems to|may be|might be|could be|"
             r"i suspect|arguably|roughly|approximately|not certain|unclear|ambiguous)\b",
    "limitation": r"\b(i (did not|didn'?t|have not|haven'?t|can'?t|cannot|couldn'?t)|"
                  r"not verified|unverified|out of scope|beyond (the )?scope|deferred|"
                  r"blocked|stopped short|not covered|did not run|untested)\b",
    "permission": r"\b(want me to|should i |shall i |let me know|do you want|"
                  r"would you like|your call|ready when you|say the word|if you want)\b",
    "selfcorrect": r"\b(correction|to correct|i was wrong|actually,|"
                   r"i mis(read|stated|understood)|earlier i said)\b",
}
LEX = {k: re.compile(v, re.I) for k, v in LEX.items()}


def project_of(path):
    d = os.path.basename(os.path.dirname(path))
    d = re.sub(r"-home-[^-]+-projects-", "", d)
    return re.sub(r"-home-[^-]+", "~", d) or d


def human_text(d):
    """Return the human's message text, or None if this isn't a real user turn."""
    if d.get("type") != "user" or d.get("isSidechain") or d.get("isMeta"):
        return None
    c = (d.get("message") or {}).get("content")
    if isinstance(c, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            return None
        c = " ".join(b.get("text", "") for b in c
                     if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(c, str) or not c.strip():
        return None
    s = c.strip()
    if s.startswith(("<system-reminder>", "<local-command", "Caveat:")):
        return None
    if s.startswith("[Request interrupted"):
        return "\x00INT"
    return s


def style(text):
    """Structural/prose metrics for a final assistant message."""
    n = len(text)
    if n < 200:
        return None
    words = text.split()
    sents = [x for x in re.split(r"(?<=[.!?])\s+|\n", text) if len(x.split()) > 2]
    m = {
        "chars": n,
        "wps": round(st.mean([len(x.split()) for x in sents]), 2) if sents else 0,
        "bullet": len(re.findall(r"^\s*[-*] ", text, re.M)),
        "header": len(re.findall(r"^#+ ", text, re.M)),
        "bold": text.count("**") // 2,
        "table": len(re.findall(r"^\|", text, re.M)),
        "tick": text.count("`"),
        "emdash": text.count("-"),
        "digit": sum(c.isdigit() for c in text),
        "uwr": round(len(set(w.lower() for w in words)) / max(1, len(words)), 3),
        "longw": sum(1 for w in words if len(w) > 9),
        "words": len(words),
    }
    for k, rx in LEX.items():
        m[k] = len(rx.findall(text))
    return m


def extract_turns(path, out, host):
    proj = project_of(path)
    cur = None
    pending = []
    session_turns = []

    def close(nxt):
        if not cur or not cur["model"] or cur["n_asst"] == 0:
            return
        seq = cur.pop("seq")
        fin = cur.pop("final")
        cur["tools"] = len(seq)
        cur["tc"] = {t: seq.count(t) for t in TRACK_TOOLS if seq.count(t)}
        disp_idx = [i for i, x in enumerate(seq) if x in DISPATCH]
        cur["dispatch"] = len(disp_idx)
        cur["post_disp"] = (len(seq) - disp_idx[-1] - 1) if disp_idx else None
        cur["style"] = style(fin)
        cur["ends_q"] = int(fin.rstrip().endswith("?"))
        cur["nudge"] = int(bool(nxt and nxt != "\x00INT" and NUDGE.match(nxt)))
        cur["interrupted"] = int(nxt == "\x00INT")
        session_turns.append(cur)

    for rec in pending:
        pass

    for line in open(path, errors="replace"):
        if '"type"' not in line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        h = human_text(d)
        if h is not None:
            close(h)
            if h == "\x00INT":
                cur = None
                continue
            cur = dict(k="turn", host=host, proj=proj, sess=d.get("sessionId"),
                       ts=d.get("timestamp"), ver=d.get("version"),
                       user_chars=len(h), model=None, effort=None,
                       n_asst=0, seq=[], text_chars=0, out_tok=0,
                       in_tok=0, cache_w_tok=0, cache_r_tok=0, final="")
            continue
        if d.get("type") == "assistant" and not d.get("isSidechain") and cur is not None:
            m = d.get("message") or {}
            if m.get("model") == "<synthetic>":
                continue
            cur["model"] = cur["model"] or m.get("model")
            cur["effort"] = cur["effort"] or d.get("effort")
            cur["n_asst"] += 1
            u = m.get("usage") or {}
            cur["out_tok"] += u.get("output_tokens") or 0
            cur["in_tok"] += u.get("input_tokens") or 0
            cur["cache_w_tok"] += u.get("cache_creation_input_tokens") or 0
            cur["cache_r_tok"] += u.get("cache_read_input_tokens") or 0
            for b in (m.get("content") or []):
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    cur["seq"].append(b.get("name"))
                elif b.get("type") == "text" and (b.get("text") or "").strip():
                    cur["text_chars"] += len(b["text"])
                    cur["final"] = b["text"]
    close(None)

    # Effort is a persistent per-session setting, emitted only on assistant
    # records and only by CLI >= ~2.1.214. Forward/back-fill it across the
    # session so a turn whose records happened not to carry it inherits the
    # active value (and a mid-session change is respected: carry last-known
    # forward). Turns in a pre-emission session stay genuinely absent -> mark
    # them "unknown" rather than null so downstream stratification buckets them
    # explicitly instead of silently pooling them with a real effort level.
    last = None
    for t in session_turns:
        if t.get("effort"):
            last = t["effort"]
        elif last:
            t["effort"] = last
    first = next((t["effort"] for t in session_turns if t.get("effort")), None)
    for t in session_turns:
        if not t.get("effort"):
            t["effort"] = first or "unknown"
        out.write(json.dumps(t, separators=(",", ":")) + "\n")


def _bump_usage(acc, model, usage):
    """Accumulate one assistant message's usage into acc[model] = {in,cache_w,cache_r,out}."""
    a = acc.setdefault(model, {"in": 0, "cache_w": 0, "cache_r": 0, "out": 0})
    a["in"] += usage.get("input_tokens") or 0
    a["cache_w"] += usage.get("cache_creation_input_tokens") or 0
    a["cache_r"] += usage.get("cache_read_input_tokens") or 0
    a["out"] += usage.get("output_tokens") or 0


def extract_session(path, out, host):
    """Per-session subagent fan-out census."""
    sid = os.path.basename(path)[:-6]
    proj = project_of(path)
    models = Counter()
    main_usage = {}  # model -> {in,cache_w,cache_r,out}, main thread only
    day = None
    for line in open(path, errors="replace"):
        if '"assistant"' not in line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") != "assistant" or d.get("isSidechain"):
            continue
        m = d.get("message") or {}
        mm = m.get("model")
        if mm and mm != "<synthetic>":
            models[mm] += 1
            day = day or (d.get("timestamp") or "")[:10]
            _bump_usage(main_usage, mm, m.get("usage") or {})
    if not models:
        return
    base = path[:-6]
    wf = glob.glob(base + "/subagents/workflows/*/agent-*.jsonl")
    plain = [f for f in glob.glob(base + "/subagents/**/*.jsonl", recursive=True)
             if "/workflows/" not in f]
    submix, subtok = Counter(), 0
    sub_usage = {}  # model -> {in,cache_w,cache_r,out}, every subagent transcript
    for f in wf + plain:
        for line in open(f, errors="replace"):
            if '"assistant"' not in line:
                continue
            try:
                x = json.loads(line)
            except Exception:
                continue
            if x.get("type") != "assistant":
                continue
            xm = x.get("message") or {}
            mm = xm.get("model")
            if mm and mm != "<synthetic>":
                submix[mm] += 1
                u = xm.get("usage") or {}
                subtok += u.get("output_tokens") or 0
                _bump_usage(sub_usage, mm, u)
    out.write(json.dumps(dict(
        k="session", host=host, sess=sid, proj=proj, day=day,
        model=models.most_common(1)[0][0], msgs=sum(models.values()),
        wf_agents=len(wf), plain_agents=len(plain),
        workflows=len({os.path.dirname(f) for f in wf}),
        sub_tok=subtok, submix=dict(submix),
        main_usage=main_usage, sub_usage=sub_usage), separators=(",", ":")) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--since", default=None, help="YYYY-MM-DD lower bound on turn ts")
    a = ap.parse_args()
    host = socket.gethostname()
    outp = a.out or os.path.expanduser(f"~/model-behavior-{host}.jsonl")
    files = sorted(glob.glob(os.path.join(a.root, "*", "*.jsonl")))
    n = 0
    with open(outp, "w") as out:
        for p in files:
            try:
                extract_turns(p, out, host)
                extract_session(p, out, host)
                n += 1
            except Exception as e:
                print(f"skip {p}: {e}")
    print(f"host={host} sessions_scanned={n} out={outp}")


if __name__ == "__main__":
    main()
