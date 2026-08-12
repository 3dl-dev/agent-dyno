# Dynamometer task suite

Each task is a JSON: {task_id, repo, ref, prompt, check?}. Use REAL extracted
repo tasks (a bug, a feature, a refactor) with a known-good outcome, replayed
identically through every engine in run-engine.py's ENGINE_CATALOG so the
efficiency vector is compared on identical terrain.

- repo:   absolute path to a git repo to branch from
- ref:    git ref to branch each run's worktree from (e.g. main, or a pre-fix SHA)
- prompt: the task instruction (the engine's orchestration directive is prepended)
- check:  optional shell command that must exit 0 for the run to count as passing

A suite is {tasks: ["fix-parser.json", ...]} (paths relative to the suite file).
