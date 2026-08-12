---
name: dyno-dynamometer
description: Run one real task through every engine (solo, orchestrator+worker, cross-model, workflow fan-out, at controlled effort) on identical terrain, then measure which engine turned the fewest tokens into the most surviving work. The clean, terrain-controlled comparison, the only way to settle "opus-drives-sonnet vs just-opus" or "wide fan-out vs sequential" with numbers instead of anecdote. Runs on your own machine and repos.
argument-hint: [a repo path + git ref + task prompt + a check command]
---

# Dyno dynamometer, controlled engine comparison

Self-contained. Read `docs/governance.md`: this compares **engines**, never
people. Observational reports are marginal over task difficulty; this fixes
difficulty by replaying one task through every engine from the same starting ref.

**Input:** $ARGUMENTS, a repo path, a git ref to branch from, the task prompt,
and a `check` command that exits 0 when the task is done right. Prefer a real
task the operator has already solved (known-good outcome), not a toy.

## The engine catalog (portable knowledge)

Each engine is a bundle: which model orchestrates, which model (if any)
implements, how work is dispatched, and the reasoning effort. Adjust to what the
operator actually runs and to their harness.

| engine | orchestrator | worker | dispatch | effort |
|---|---|---|---|---|
| solo | strong | - | does it itself | high |
| solo-max | strong | - | itself | max |
| delegate-cheap | strong | cheaper | delegate to a worker subagent | high |
| delegate-strong | strong | strong | delegate to a worker subagent | high |
| workflow | strong | strong | fan out independent parts | high |

## Run one engine

In a fresh throwaway git worktree per engine (`git worktree add`):
1. If the engine has a worker model, pin it in the harness's subagent config
   (for Claude Code: `.claude/agents/impl-worker.md` frontmatter `model:`).
2. Prepend the engine's dispatch directive to the task prompt (solo: "do it
   yourself"; delegate: "delegate implementation to your worker, you review";
   workflow: "decompose and fan out, then synthesize").
3. Invoke the harness's headless mode at the engine's effort; record the session id.
4. Run the task's `check`; note pass/fail.

## Spend guardrail

A full matrix is `tasks × engines` real sessions, real tokens. **Print the plan
and get explicit go before running.** Never launch a matrix unprompted.

## Measure and present

Apply `dyno-report` to each session. Because terrain is constant, differences are
the engine. Report the vector per engine (Pareto), which engine passed `check` at
the lowest $/surviving-KB and waste, and the model×harness read. Vary **effort as
a controlled factor** (the catalog has solo-max), do not leave it at default.

A reference implementation of this exact procedure ships at
`adapters/claude-code/` (see the dynamometer runner); it is convenience for that
harness, not a dependency of this skill.
