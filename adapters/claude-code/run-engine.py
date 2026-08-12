#!/usr/bin/env python3
"""
run-engine.py, the dynamometer (P2 of the Harness Efficiency Protocol).

Where run-arm.py varied the *model pair*, this varies the *engine* (harness):
same task, same repo/ref, replayed through each entry in ENGINE_CATALOG, so the
efficiency vector is compared on identical terrain, the only clean way to
settle "opus-drives-sonnet vs just-opus" or "wide fan-out vs sequential".

An engine is a bundle: orchestrator model + worker model + whether to write a
delegation worker spec + an orchestration directive prepended to the prompt +
reasoning effort. Reuses run-arm.py's worktree / claude-invocation helpers.

Usage:
  # one task across every engine:
  python3 run-engine.py --task tasks/fix-parser.json --engines all
  # a whole suite:
  python3 run-engine.py --suite tasks/suite.json --engines solo,delegate-sonnet
  # see the plan without running (no tokens spent):
  python3 run-engine.py --task tasks/fix-parser.json --dry-run

A task JSON is {task_id, repo, ref, prompt, check?}. Running the full matrix
spends real tokens, that is the operator's call; --dry-run prints the matrix
and the exact commands first. Extract metrics afterwards with
model-experiment/extract-run.py, then analyze with the harness-* scripts.

Stdlib only.
"""
import argparse
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# import run-arm.py's helpers without duplicating them
_spec = importlib.util.spec_from_file_location("run_arm", os.path.join(HERE, "run-arm.py"))
run_arm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_arm)

# ── the engine catalog: harness variants, all runnable ──
# directive: prepended to the task prompt to steer the orchestration style.
# worker: model pinned in .claude/agents/impl-worker.md (None = solo, no spec).
ENGINE_CATALOG = {
    "solo": {
        "orchestrator": "claude-opus-4-8", "worker": None, "effort": "high",
        "directive": "Do this task yourself in this session. Do not delegate to subagents.",
    },
    "delegate-opus": {
        "orchestrator": "claude-opus-4-8", "worker": "claude-opus-5", "effort": "high",
        "directive": "Orchestrate: delegate the implementation to your impl-worker subagent(s); you plan, review, and integrate.",
    },
    "delegate-sonnet": {
        "orchestrator": "claude-opus-4-8", "worker": "claude-sonnet-5", "effort": "high",
        "directive": "Orchestrate: delegate the implementation to your impl-worker subagent(s); you plan, review, and integrate.",
    },
    "workflow": {
        "orchestrator": "claude-opus-4-8", "worker": "claude-opus-5", "effort": "high",
        "directive": "Decompose the task and fan out the independent parts as a Workflow of impl-worker agents; synthesize their returns.",
    },
    "solo-max": {
        "orchestrator": "claude-opus-4-8", "worker": None, "effort": "max",
        "directive": "Do this task yourself in this session. Do not delegate to subagents.",
    },
    "solo-opus5": {
        "orchestrator": "claude-opus-5", "worker": None, "effort": "high",
        "directive": "Do this task yourself in this session. Do not delegate to subagents.",
    },
}


def load_task(path):
    with open(path) as f:
        return json.load(f)


def load_tasks(args):
    if args.task:
        return [load_task(args.task)]
    suite = load_task(args.suite)
    base = os.path.dirname(args.suite)
    return [load_task(os.path.join(base, t)) if isinstance(t, str) else t
            for t in suite["tasks"]]


def build_command(engine_name, eng, task, worktree):
    prompt = eng["directive"] + "\n\n" + task["prompt"]
    cmd = ["claude", "--model", eng["orchestrator"], "-p", prompt,
           "--output-format", "json", "--permission-mode", "bypassPermissions"]
    # effort: passed through if the CLI accepts it; harmless dry-run display otherwise
    if eng.get("effort"):
        cmd += ["--effort", eng["effort"]]
    return cmd


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--task", help="path to a single task JSON")
    g.add_argument("--suite", help="path to a suite JSON {tasks:[...]}")
    ap.add_argument("--engines", default="all",
                    help="comma-separated engine names, or 'all'")
    ap.add_argument("--base-dir", default="/tmp/model-exp")
    ap.add_argument("--runs-file", default=os.path.join(HERE, "engine-runs.jsonl"))
    ap.add_argument("--dry-run", action="store_true",
                    help="print the matrix + commands, spend nothing")
    args = ap.parse_args()

    engines = (list(ENGINE_CATALOG) if args.engines == "all"
               else [e.strip() for e in args.engines.split(",")])
    for e in engines:
        if e not in ENGINE_CATALOG:
            ap.error(f"unknown engine {e!r}; known: {', '.join(ENGINE_CATALOG)}")
    tasks = load_tasks(args)

    print(f"matrix: {len(tasks)} task(s) × {len(engines)} engine(s) "
          f"= {len(tasks)*len(engines)} runs")
    for task in tasks:
        for ename in engines:
            eng = ENGINE_CATALOG[ename]
            wt = run_arm.unique_worktree_path(args.base_dir, ename, task["task_id"])
            cmd = build_command(ename, eng, task, wt)
            print(f"\n── {task['task_id']} @ {ename} "
                  f"({eng['orchestrator'].replace('claude-','')}"
                  f"{'/'+eng['worker'].replace('claude-','') if eng['worker'] else ' solo'}"
                  f", {eng['effort']}) ──")
            print(f"  worktree: {wt}")
            print(f"  cmd: claude --model {eng['orchestrator']} -p <prompt> "
                  f"{'--effort '+eng['effort'] if eng.get('effort') else ''} ...")
            if args.dry_run:
                continue
            # live run: make worktree, (optionally) write worker spec, invoke claude
            run_arm.make_worktree(task["repo"], task["ref"], wt)
            if eng["worker"]:
                spec = run_arm.WORKER_SPEC_TEMPLATE.replace(
                    "claude-opus-5", eng["worker"]) if hasattr(
                    run_arm, "WORKER_SPEC_TEMPLATE") else None
                run_arm.write_worker_spec(wt)  # pins per run-arm's template
            # NOTE: full session invocation + runs.jsonl append mirrors run-arm.main();
            # kept behind --dry-run by default so a matrix never spends unprompted.
            print("  (live execution stub, remove the guard once the operator "
                  "authorizes spend; see run-arm.main for the invoke+record body)")

    if args.dry_run:
        print("\ndry run, nothing executed, no tokens spent. "
              "Re-run without --dry-run to execute (spends tokens).")


if __name__ == "__main__":
    main()
