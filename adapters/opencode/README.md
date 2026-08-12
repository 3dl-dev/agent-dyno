# adapters/opencode — slot

Adapter slot for the **OpenCode** harness. Not yet implemented.

To build it: emit the common schema (see `adapters/claude-code/README.md` and
`docs/protocol.md`) from OpenCode's session logs. As with every harness, the
git-based numerator (`core/survival_git.py`) already measures OpenCode-produced
code with no adapter; this slot only adds the fuel/fingerprint side. PRs welcome.
