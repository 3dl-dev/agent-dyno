#!/usr/bin/env python3
"""
fingerprint_evidence.py, package per-rig evidence for the pattern classifier.

Three of the six taxonomy dimensions (docs/taxonomy.md) are patterns, not counts:
fine topology, review regime, knowledge practice. A counter cannot place them, so
the in-session model classifies them once and caches the result in
fingerprint-labels.json, which the vibrant_report driver consumes deterministically.

This extractor produces the INPUT to that classification: a compact evidence
bundle per RIG (the driver's join key, engine/routing/effort), so the model reads
signal, never raw transcripts. It is harness-specific (it reads Claude Code
transcripts); the labels it helps produce are harness-neutral.

Evidence per rig:
  - skills:         skill invocations (knowledge practice; nearly deterministic)
  - bash:           Bash commands tagged test / lint / vcs / shell (review regime)
  - subagent_tasks: a deduped sample of Task/Agent prompts (fine topology)
  - fanout_width_mean, sessions

Usage:
  python3 fingerprint_evidence.py --snapshot <snap-dir> [--projects DIR] [--out PATH]
  python3 fingerprint_evidence.py --selftest        # fixture self-check, exits 0/1
Stdlib only. Reads the snapshot's mb-*.jsonl for the rig skeleton and the raw
transcripts for the pattern evidence.
"""
import argparse
import glob
import json
import os
import re
import sys
import tempfile
from collections import defaultdict, Counter

DEFAULT_PROJECTS = os.path.expanduser("~/.claude/projects")
SCHEMA = "vibrant/fingerprint-evidence@1"
MAX_TASKS = 20        # deduped sample of subagent prompts per rig
TASK_CHARS = 140      # truncate each prompt to keep the bundle compact

TEST_RE = re.compile(r"\b(pytest|unittest|nose|jest|mocha|vitest|go test|"
                     r"cargo test|npm (run )?test|yarn test|make test|rspec|"
                     r"phpunit|ctest|tox)\b", re.I)
LINT_RE = re.compile(r"\b(ruff|flake8|pylint|mypy|black|isort|eslint|prettier|"
                     r"gofmt|golangci-lint|clippy|rustfmt|shellcheck|lint|"
                     r"tsc|type-?check)\b", re.I)
VCS_RE = re.compile(r"^\s*(git|gh|hg|svn)\b")


def base(m):
    return (m or "").split("[")[0].replace("claude-", "")


def engine_of(sess):
    if (sess.get("workflows") or 0) > 0 or (sess.get("wf_agents") or 0) > 0:
        return "workflow"
    if (sess.get("plain_agents") or 0) > 0:
        return "delegate"
    return "solo"


def routing_of(sess):
    submix = sess.get("submix") or {}
    if not submix:
        return "none"
    orch = base(sess.get("model"))
    worker_bases = {base(m) for m in submix}
    return "homogeneous" if worker_bases == {orch} else "cross-family"


def modal(values, default="unknown"):
    if not values:
        return default
    counts = Counter(values)
    return sorted(counts, key=lambda v: (-counts[v], v))[0]


def load_rigs(snapshot):
    """sess_id -> rig key (engine/routing/effort), from the snapshot mb records."""
    sess, efforts, fanout = {}, defaultdict(list), {}
    for p in glob.glob(os.path.join(snapshot, "mb-*.jsonl")) + \
            glob.glob(os.path.join(snapshot, "*", "mb-*.jsonl")):
        for line in open(p):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("k") == "session":
                sess[r["sess"]] = r
            elif r.get("k") == "turn" and r.get("effort"):
                efforts[r["sess"]].append(r["effort"])
    rig_of = {}
    for sid, s in sess.items():
        effort = modal(efforts.get(sid, []), default="unknown")
        rig_of[sid] = f"{engine_of(s)}/{routing_of(s)}/{effort}"
        fanout[sid] = (s.get("wf_agents") or 0) + (s.get("plain_agents") or 0)
    return rig_of, fanout


def tag_bash(cmd):
    if TEST_RE.search(cmd):
        return "test"
    if LINT_RE.search(cmd):
        return "lint"
    if VCS_RE.match(cmd):
        return "vcs"
    return "shell"


def scan_transcripts(projects, rig_of):
    """Read raw transcripts; return per-session evidence for sessions we have a
    rig for. Evidence: skill Counter, bash-tag Counter, subagent task list."""
    ev = defaultdict(lambda: {"skills": Counter(), "bash": Counter(), "tasks": []})
    for mp in glob.glob(os.path.join(projects, "*", "*.jsonl")):
        sid = os.path.basename(mp)[:-6]
        if sid not in rig_of:
            continue
        try:
            fh = open(mp)
        except Exception:
            continue
        e = ev[sid]
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            content = (d.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if b.get("type") != "tool_use":
                    continue
                name = b.get("name")
                inp = b.get("input") or {}
                if name == "Skill":
                    nm = inp.get("skill") or inp.get("name")
                    if nm:
                        e["skills"][nm] += 1
                elif name == "Bash":
                    cmd = inp.get("command") or ""
                    if cmd:
                        e["bash"][tag_bash(cmd)] += 1
                elif name in ("Task", "Agent"):
                    desc = inp.get("description") or inp.get("prompt") or ""
                    if desc:
                        e["tasks"].append(desc.strip()[:TASK_CHARS])
    return ev


def build(snapshot, projects):
    rig_of, fanout = load_rigs(snapshot)
    ev = scan_transcripts(projects, rig_of)
    rigs = {}
    agg = defaultdict(lambda: {"skills": Counter(), "bash": Counter(),
                               "tasks": [], "sessions": 0, "fanout": []})
    for sid, rig in rig_of.items():
        a = agg[rig]
        a["sessions"] += 1
        a["fanout"].append(fanout.get(sid, 0))
        e = ev.get(sid)
        if e:
            a["skills"] += e["skills"]
            a["bash"] += e["bash"]
            a["tasks"].extend(e["tasks"])
    for rig, a in sorted(agg.items()):
        tasks = []
        seen = set()
        for t in a["tasks"]:  # dedup, stable order, capped
            if t not in seen:
                seen.add(t)
                tasks.append(t)
            if len(tasks) >= MAX_TASKS:
                break
        fw = a["fanout"]
        rigs[rig] = {
            "sessions": a["sessions"],
            "skills": dict(sorted(a["skills"].items())),
            "bash": dict(sorted(a["bash"].items())),
            "subagent_tasks": tasks,
            "fanout_width_mean": round(sum(fw) / len(fw), 1) if fw else 0,
        }
    return {"schema": SCHEMA, "taxonomy": "docs/taxonomy.md",
            "produces": "fingerprint-labels.json", "rigs": rigs}


def selftest():
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "snap"); os.makedirs(snap)
        proj = os.path.join(tmp, "proj", "p"); os.makedirs(proj)
        # one delegate/none/high session "sX"
        recs = [
            {"k": "session", "sess": "sX", "model": "claude-opus-5", "submix": {},
             "workflows": 0, "wf_agents": 0, "plain_agents": 2},
            {"k": "turn", "sess": "sX", "effort": "high"},
        ]
        with open(os.path.join(snap, "mb-h.jsonl"), "w") as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")
        # transcript sX.jsonl: a Skill, a test Bash, a shell Bash, a Task
        lines = [
            {"message": {"content": [{"type": "tool_use", "name": "Skill",
                                      "input": {"skill": "code-review"}}]}},
            {"message": {"content": [{"type": "tool_use", "name": "Bash",
                                      "input": {"command": "python3 -m pytest"}}]}},
            {"message": {"content": [{"type": "tool_use", "name": "Bash",
                                      "input": {"command": "ls -la"}}]}},
            {"message": {"content": [{"type": "tool_use", "name": "Task",
                                      "input": {"description": "review the diff"}}]}},
        ]
        with open(os.path.join(proj, "sX.jsonl"), "w") as f:
            for r in lines:
                f.write(json.dumps(r) + "\n")
        out = build(snap, os.path.join(tmp, "proj"))
        rig = out["rigs"].get("delegate/none/high")
        if not rig:
            fails.append("rig delegate/none/high not built")
        else:
            if rig["skills"].get("code-review") != 1:
                fails.append(f"skill evidence wrong: {rig['skills']}")
            if rig["bash"].get("test") != 1 or rig["bash"].get("shell") != 1:
                fails.append(f"bash tagging wrong: {rig['bash']}")
            if "review the diff" not in rig["subagent_tasks"]:
                fails.append(f"subagent task not captured: {rig['subagent_tasks']}")
            if rig["fanout_width_mean"] != 2.0:
                fails.append(f"fanout mean wrong: {rig['fanout_width_mean']}")
    if fails:
        print("FAIL  fingerprint_evidence:")
        for f in fails:
            print("  -", f)
        return 1
    print("PASS  fingerprint_evidence: rig keying, bash tagging, evidence bundling")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", help="snapshot dir (mb-*.jsonl) for rig skeletons")
    ap.add_argument("--projects", default=DEFAULT_PROJECTS,
                    help="raw transcript root (default ~/.claude/projects)")
    ap.add_argument("--out", default=None, help="write evidence JSON here (else stdout)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.snapshot:
        ap.error("--snapshot is required (or use --selftest)")
    out = build(args.snapshot, os.path.expanduser(args.projects))
    text = json.dumps(out, indent=2, sort_keys=True) + "\n"
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"evidence written: {args.out} ({len(out['rigs'])} rigs)")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
