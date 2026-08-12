#!/usr/bin/env python3
"""
extract-run.py — per-run metrics for the model-configuration experiment
(resonant-321), using the SAME definitions as
the sibling model-behavior.py and model-behavior-code.py in this adapter
(imported directly from this directory — not re-derived).

    python3 extract-run.py --runs-file runs.jsonl [--out metrics-runs.jsonl]
    python3 extract-run.py <session_id> [<session_id> ...] [--out metrics-runs.jsonl]

For each run, locates the session's transcript under
~/.claude/projects/<slug>/<session_id>.jsonl (searched across all project
slugs, since a worktree's slug isn't reconstructed here), then walks the main
thread plus every subagents/**/*.jsonl transcript beneath it.

Reused verbatim from model-behavior.py / model-behavior-code.py:
  - "turn" extraction (tool sequence, dispatch detection, post-dispatch tool
    count, output tokens, final-message style/regex metrics) via
    mb.extract_turns
  - subagent fan-out + their output-token total via mb.extract_session
  - Edit/Write call counts, chars written, and failed-tool-result detection
    (is_error / "Error:" / "String to replace not found" / "has not been read
    yet") via mc.scan, run once over the main thread and once over every
    subagent transcript

Per-run record (metrics-runs.jsonl, one line each):
  session_id, arm, task_id, orchestrator_model (from runs.jsonl if given),
  edits_main, edits_sub, edits_total,
  chars_written_main, chars_written_sub, chars_written_total,
  failed_tool_results_main, failed_tool_results_sub, failed_tool_results_total,
  output_tokens_main, output_tokens_sub, output_tokens_total,
  tool_calls_after_last_dispatch, dispatch_count,
  ask_user_question_count,
  final_text_chars, regex_hits {permission, limitation, caveat, hedge},
  main_models_seen {model: assistant-message-count},
  worker_models_seen {model: assistant-message-count},
  wf_agents, plain_agents (subagent fan-out counts, from mb.extract_session)

Python 3 stdlib only.
"""
import argparse
import glob
import importlib.util
import io
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
TELEMETRY_DIR = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(HERE, "metrics-runs.jsonl")
DEFAULT_RUNS_FILE = os.path.join(HERE, "runs.jsonl")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mb = _load("model_behavior", os.path.join(TELEMETRY_DIR, "model-behavior.py"))
mc = _load("model_behavior_code", os.path.join(TELEMETRY_DIR, "model-behavior-code.py"))


def find_session_path(session_id):
    matches = glob.glob(
        os.path.expanduser(f"~/.claude/projects/*/{session_id}.jsonl")
    )
    if not matches:
        return None
    # Prefer the most recently modified if somehow more than one matches
    # (shouldn't happen — session ids are UUIDs — but be defensive).
    matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return matches[0]


def model_census(paths, main_thread_only):
    """Count assistant messages per model across the given transcript files."""
    counts = Counter()
    for p in paths:
        try:
            fh = open(p, errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"assistant"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") != "assistant":
                    continue
                if main_thread_only and d.get("isSidechain"):
                    continue
                m = (d.get("message") or {}).get("model")
                if m and m != "<synthetic>":
                    counts[m] += 1
    return counts


def extract_one(session_path):
    session_dir = session_path[:-6]  # strip ".jsonl"
    subagent_files = glob.glob(os.path.join(session_dir, "subagents", "**", "*.jsonl"), recursive=True)

    # --- reuse mb.extract_turns / mb.extract_session verbatim, via an in-memory buffer ---
    turns_buf = io.StringIO()
    mb.extract_turns(session_path, turns_buf, host="exp")
    turn_records = [json.loads(line) for line in turns_buf.getvalue().splitlines() if line.strip()]

    sess_buf = io.StringIO()
    mb.extract_session(session_path, sess_buf, host="exp")
    sess_lines = [json.loads(line) for line in sess_buf.getvalue().splitlines() if line.strip()]
    sess_record = sess_lines[0] if sess_lines else {}

    output_tokens_main = sum(t.get("out_tok", 0) for t in turn_records)
    dispatch_count = sum(t.get("dispatch", 0) for t in turn_records)
    ask_user_question_count = sum(t.get("tc", {}).get("AskUserQuestion", 0) for t in turn_records)

    # "Tool calls after last dispatch" and the regex hits on final text: taken
    # from the LAST turn in the run (a headless single-prompt run is normally
    # exactly one turn; if more than one occurred, the last is the one whose
    # final text a human would actually read).
    last_turn = turn_records[-1] if turn_records else {}
    tool_calls_after_last_dispatch = last_turn.get("post_disp")
    style = last_turn.get("style") or {}
    regex_hits = {
        "permission": style.get("permission", 0),
        "limitation": style.get("limitation", 0),
        "caveat": style.get("caveat", 0),
        "hedge": style.get("hedge", 0),
    }
    final_text_chars = style.get("chars", 0)

    # --- reuse mc.scan verbatim for edits / chars / failed tool results ---
    orch, orch_files = mc.blank(), Counter()
    mc.scan([session_path], True, orch, orch_files)
    work, work_files = mc.blank(), Counter()
    if subagent_files:
        mc.scan(subagent_files, False, work, work_files)

    main_models_seen = dict(model_census([session_path], main_thread_only=True))
    worker_models_seen = dict(model_census(subagent_files, main_thread_only=False))

    return {
        "session_id": os.path.basename(session_path)[:-6],
        "edits_main": orch.get("edits", 0),
        "edits_sub": work.get("edits", 0),
        "edits_total": orch.get("edits", 0) + work.get("edits", 0),
        "chars_written_main": orch.get("edit_chars", 0),
        "chars_written_sub": work.get("edit_chars", 0),
        "chars_written_total": orch.get("edit_chars", 0) + work.get("edit_chars", 0),
        "failed_tool_results_main": orch.get("errors", 0),
        "failed_tool_results_sub": work.get("errors", 0),
        "failed_tool_results_total": orch.get("errors", 0) + work.get("errors", 0),
        "output_tokens_main": output_tokens_main,
        "output_tokens_sub": sess_record.get("sub_tok", 0),
        "output_tokens_total": output_tokens_main + sess_record.get("sub_tok", 0),
        "tool_calls_after_last_dispatch": tool_calls_after_last_dispatch,
        "dispatch_count": dispatch_count,
        "ask_user_question_count": ask_user_question_count,
        "final_text_chars": final_text_chars,
        "regex_hits": regex_hits,
        "main_models_seen": main_models_seen,
        "worker_models_seen": worker_models_seen,
        "wf_agents": sess_record.get("wf_agents", 0),
        "plain_agents": sess_record.get("plain_agents", 0),
        "n_turns": len(turn_records),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session_ids", nargs="*", help="session ids to extract (omit to use --runs-file)")
    ap.add_argument("--runs-file", default=None, help=f"runs.jsonl to read (default {DEFAULT_RUNS_FILE} if no session ids given)")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"output path (default {DEFAULT_OUT})")
    args = ap.parse_args()

    run_meta = {}  # session_id -> run record fields to merge in
    session_ids = list(args.session_ids)

    runs_file = args.runs_file
    if not session_ids and runs_file is None:
        runs_file = DEFAULT_RUNS_FILE
    if runs_file and os.path.exists(runs_file):
        with open(runs_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                sid = rec.get("session_id")
                if not sid:
                    continue
                run_meta[sid] = rec
                if sid not in session_ids:
                    session_ids.append(sid)
    elif runs_file and not os.path.exists(runs_file) and not args.session_ids:
        sys.exit(f"no session ids given and runs file not found: {runs_file}")

    if not session_ids:
        sys.exit("no session ids to extract (pass session ids or --runs-file)")

    n_ok = 0
    with open(args.out, "w") as out:
        for sid in session_ids:
            path = find_session_path(sid)
            if not path:
                print(f"skip {sid}: no transcript found under ~/.claude/projects/*/", file=sys.stderr)
                continue
            try:
                rec = extract_one(path)
            except Exception as e:
                print(f"skip {sid}: {e}", file=sys.stderr)
                continue
            meta = run_meta.get(sid, {})
            for k in ("arm", "task_id", "orchestrator_model", "wall_seconds", "exit_code", "worktree"):
                if k in meta:
                    rec[k] = meta[k]
            out.write(json.dumps(rec) + "\n")
            n_ok += 1

    print(f"wrote {n_ok}/{len(session_ids)} records to {args.out}")


if __name__ == "__main__":
    main()
