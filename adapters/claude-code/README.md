# adapters/claude-code

The first harness adapter. Reads Claude Code session transcripts under
`~/.claude/projects/**/*.jsonl` (main + `subagents/`) and computes the
harness-specific side of the efficiency vector: priced tokens, engine class,
model routing, reasoning effort, review signals, and same-session waste. The
harness-neutral numerator (`core/survival_git.py`) supplies surviving work.

Python 3, stdlib only. No install.

## What's here

- `model-behavior.py`, `model-behavior-code.py` — per-turn / per-session /
  per-code extractors (tokens, tools, effort, orchestrator vs worker split).
- `model-behavior-survival.py` — same-session waste (the survival floor).
- `mb_cost.py` + `prices.json` — full dollar accounting; edit `prices.json` to
  add models or update rates (never hardcode IDs elsewhere).
- `harness-characterize.py` — engine classes + engine×model entanglement.
- `harness-efficiency.py` — the efficiency vector + Pareto frontier.
- `harness-fingerprint.py` — granular setups + the delegation cold-read test.
- `harness-modeleffect.py` — model effect at fixed harness + interaction.
- `harness-readcost.py` — is cost O(reads).
- `harness-switchcost.py` — mid-session model-switch tax.
- `harness-subagenttax.py` — per-subagent cold-prefill tax.
- `run-engine.py` + `run-arm.py` — the dynamometer: one task through every engine
  (see `skills/dyno-dynamometer`). `--dry-run` plans the matrix and spends nothing.

## Common schema (what every adapter must emit)

An adapter's job is to normalize its harness into records the analyses consume:
per **turn** (model, effort, tokens {input, output, cache_write, cache_read},
tool counts, dispatch), per **session** (model, subagent census, worker token
mix), and per **code** action (edits, chars, tests, commits, reverts, orchestrator
vs worker split). A new harness re-implements only this normalization; it does not
fork the analyses. See `docs/protocol.md`.
