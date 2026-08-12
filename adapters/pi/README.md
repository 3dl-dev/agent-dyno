# adapters/pi, slot

Adapter slot for the **pi** harness. Not yet implemented.

To build it: emit the common schema (see `adapters/claude-code/README.md` and
`docs/protocol.md`) from pi's own session logs, per-turn tokens + model +
effort, per-session subagent census, per-code edit/commit/revert counts. The
harness-neutral numerator (`core/survival_git.py`) already works for pi-produced
code with no adapter, since it reads git. Only the fuel/fingerprint side needs
this slot filled. PRs welcome.
