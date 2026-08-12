#!/usr/bin/env python3
"""
run-arm.py — arm-runner harness for the orchestrator/subagent model-configuration
experiment (resonant-321).

    python3 run-arm.py <arm> <task-id> --repo <path> --ref <git-ref> --prompt-file <path>

Arms (orchestrator model):
    A = claude-opus-4-8
    B = claude-opus-5
    C = claude-fable-5

For every arm, the subagent worker spec (.claude/agents/impl-worker.md) pins
`model: claude-opus-5` in its YAML frontmatter. This is the only reliable way to
pin a subagent to Opus 5 from a session driven by any other model: the Agent
tool's `model` parameter is an enum (`sonnet|opus|haiku|fable`) with no way to
name a specific generation's Opus tier, and it resolves aliases within the
*driving session's* model family — from an Opus 4.8 session, `model: "opus"`
resolves to Opus 4.8, not Opus 5. An agent spec's frontmatter, by contrast,
takes a full model ID.

Behavior:
  1. Create a throwaway git worktree of --repo at --ref, under
     /tmp/model-exp/<arm>-<task-id>-<n> (n auto-increments to avoid collisions).
  2. Write .claude/agents/impl-worker.md into the worktree, pinning the worker
     model to claude-opus-5 for every arm.
  3. Run `claude --model <orchestrator-id> -p "<prompt>" --output-format json`
     from inside the worktree, capturing stdout to a per-run log.
  4. Append one line to runs.jsonl: {arm, task_id, orchestrator_model,
     session_id, start_iso, end_iso, wall_seconds, exit_code, worktree,
     log_path}.
  5. Clean up the worktree on success, unless --keep is passed (failures are
     always left in place for post-mortem).

Python 3 stdlib only.
"""
import argparse
import datetime
import glob
import json
import os
import subprocess
import sys
import time

ARM_MODELS = {
    "A": "claude-opus-4-8",
    "B": "claude-opus-5",
    "C": "claude-fable-5",
}

WORKER_MODEL = "claude-opus-5"

WORKER_SPEC = f"""---
name: impl-worker
description: General implementation worker for delegated coding tasks — writing files, running commands, editing code. Use this agent for any generic subagent work in this session.
model: {WORKER_MODEL}
---

You are a general-purpose implementation worker. Complete the task you are
given directly and completely, then report back concisely on what you did.
"""

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RUNS_FILE = os.path.join(HERE, "runs.jsonl")
DEFAULT_BASE_DIR = "/tmp/model-exp"


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def slug_for(path):
    """Same slugging scheme Claude Code uses under ~/.claude/projects/<slug>/:
    every '/' and '.' in the absolute cwd path becomes '-'."""
    return path.replace("/", "-").replace(".", "-")


def unique_worktree_path(base_dir, arm, task_id):
    os.makedirs(base_dir, exist_ok=True)
    n = 1
    while True:
        candidate = os.path.join(base_dir, f"{arm}-{task_id}-{n}")
        if not os.path.exists(candidate):
            return candidate
        n += 1


def make_worktree(repo, ref, path):
    repo = os.path.abspath(repo)
    cmd = ["git", "-C", repo, "worktree", "add", "--detach", path, ref]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(
            f"git worktree add failed (repo={repo!r}, ref={ref!r}, path={path!r}):\n"
            f"{r.stdout}\n{r.stderr}"
        )
    return repo


def remove_worktree(repo, path):
    subprocess.run(
        ["git", "-C", repo, "worktree", "remove", "--force", path],
        capture_output=True,
        text=True,
    )


def write_worker_spec(worktree):
    agents_dir = os.path.join(worktree, ".claude", "agents")
    os.makedirs(agents_dir, exist_ok=True)
    spec_path = os.path.join(agents_dir, "impl-worker.md")
    with open(spec_path, "w") as f:
        f.write(WORKER_SPEC)
    return spec_path


def find_session_id_from_stdout(stdout_text):
    """--output-format json emits a single JSON object; look for a session id
    field under a few plausible names."""
    try:
        obj = json.loads(stdout_text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    for key in ("session_id", "sessionId", "session", "id", "uuid"):
        v = obj.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def discover_session_id(worktree, started_after):
    """Fallback: find the newest session JSONL under ~/.claude/projects/<slug>/
    for this worktree's path, created at/after `started_after` (epoch seconds)."""
    slug = slug_for(os.path.abspath(worktree))
    proj_dir = os.path.expanduser(os.path.join("~/.claude/projects", slug))
    candidates = glob.glob(os.path.join(proj_dir, "*.jsonl"))
    best, best_mtime = None, None
    for c in candidates:
        try:
            mtime = os.path.getmtime(c)
        except OSError:
            continue
        if mtime + 2 < started_after:  # small slack for clock skew
            continue
        if best_mtime is None or mtime > best_mtime:
            best, best_mtime = c, mtime
    if not best:
        return None
    return os.path.basename(best)[:-6]  # strip ".jsonl"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("arm", choices=sorted(ARM_MODELS), help="A, B, or C")
    ap.add_argument("task_id", help="identifier for this task, used in the worktree path and runs.jsonl")
    ap.add_argument("--repo", required=True, help="path to the task repo")
    ap.add_argument("--ref", required=True, help="git ref to check out into the worktree")
    ap.add_argument("--prompt-file", required=True, help="path to a file containing the prompt text")
    ap.add_argument("--base-dir", default=DEFAULT_BASE_DIR, help=f"parent dir for worktrees (default {DEFAULT_BASE_DIR})")
    ap.add_argument("--runs-file", default=DEFAULT_RUNS_FILE, help="runs.jsonl path to append to")
    ap.add_argument("--keep", action="store_true", help="keep the worktree even on success")
    ap.add_argument(
        "--force-skip-permissions",
        action="store_true",
        help="add --dangerously-skip-permissions (only if bypassPermissions still stalls on prompts)",
    )
    ap.add_argument("--permission-mode", default="bypassPermissions", help="passed through to claude --permission-mode")
    ap.add_argument("--timeout-seconds", type=int, default=900, help="hard wall-clock cap per run")
    args = ap.parse_args()

    orchestrator_model = ARM_MODELS[args.arm]

    with open(args.prompt_file) as f:
        prompt_text = f.read()

    worktree = unique_worktree_path(args.base_dir, args.arm, args.task_id)
    repo_abs = make_worktree(args.repo, args.ref, worktree)
    write_worker_spec(worktree)

    logs_dir = os.path.join(args.base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    run_name = os.path.basename(worktree)
    stdout_log = os.path.join(logs_dir, f"{run_name}.stdout.log")
    stderr_log = os.path.join(logs_dir, f"{run_name}.stderr.log")

    cmd = [
        "claude",
        "--model", orchestrator_model,
        "-p", prompt_text,
        "--output-format", "json",
        "--permission-mode", args.permission_mode,
    ]
    if args.force_skip_permissions:
        cmd.append("--dangerously-skip-permissions")

    start_iso = now_iso()
    start_epoch = time.time()
    timed_out = False
    try:
        r = subprocess.run(
            cmd,
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=args.timeout_seconds,
        )
        stdout_text, stderr_text, exit_code = r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired as e:
        timed_out = True
        stdout_text = e.stdout or ""
        stderr_text = (e.stderr or "") + "\n[run-arm.py] TIMEOUT after {}s\n".format(args.timeout_seconds)
        exit_code = -1
    end_iso = now_iso()
    wall_seconds = round(time.time() - start_epoch, 3)

    with open(stdout_log, "w") as f:
        f.write(stdout_text)
    with open(stderr_log, "w") as f:
        f.write(stderr_text)

    session_id = find_session_id_from_stdout(stdout_text) or discover_session_id(worktree, start_epoch)

    record = {
        "arm": args.arm,
        "task_id": args.task_id,
        "orchestrator_model": orchestrator_model,
        "session_id": session_id,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "wall_seconds": wall_seconds,
        "exit_code": exit_code,
        "worktree": worktree,
        "log_path": stdout_log,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.runs_file)), exist_ok=True)
    with open(args.runs_file, "a") as f:
        f.write(json.dumps(record) + "\n")

    print(json.dumps(record, indent=2))

    ok = (exit_code == 0) and not timed_out
    if ok and not args.keep:
        remove_worktree(repo_abs, worktree)
    else:
        reason = "non-zero exit" if exit_code != 0 else ("timeout" if timed_out else "--keep")
        print(f"[run-arm.py] worktree kept at {worktree} ({reason})", file=sys.stderr)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
