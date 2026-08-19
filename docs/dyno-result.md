# Dynamometer: the difficulty-controlled comparison (2026-08-19)

The observational report is confounded by task difficulty (a lean setup can look efficient just
by doing easier, stickier work, see `claims.md`, "Selection confound"). The dynamometer removes
the confound by construction: run ONE fixed task through each engine on identical terrain, so
survival is not a difficulty proxy and the efficiency gap is real token-thrift.

## The run

One fixed, verifiable task (implement `roman(n)` + a passing test suite), same starting point,
through two engine shapes in isolated worktrees:

| engine | check | surviving lines | output tokens | efficiency (lines/Mtok) | survival |
|--------|:-----:|----------------:|--------------:|------------------------:|:--------:|
| solo | pass | 24 | 28,214 | 851 | 100% |
| workflow (fan-out, 2 workers) | pass | 24 | 33,512 | 716 | 100% |

## What it shows

Both engines produced identical, fully-surviving work (24 lines, test green, nothing reverted),
so there is NO survival-rate difference to confound the comparison, unlike the observational
data. The whole efficiency gap is production-rate: solo made the same result for ~19% fewer
tokens, because the fan-out spent tokens on coordination (two workers each re-reading context)
that a small task does not repay.

So for a task this size, solo is genuinely the thriftier engine, confirmed on identical terrain,
not because it was handed easier work.

## The suite: does fan-out ever repay its overhead? (a larger task)

Added a larger, genuinely decomposable task, five independent modules (roman/unroman, RLE,
Levenshtein, RFC-4648 base32) behind one combined test, run through both engines from the same
spec (fixed functional cargo, both passed the identical check):

| task | engine | tokens to a passing result | wall-clock | check |
|------|--------|---------------------------:|-----------:|:-----:|
| small (1 module) | solo | 28,214 | 18s | pass |
| small | workflow (2 workers) | 33,512 (+19%) | 31s | pass |
| large (5 modules) | solo | 32,086 | 51s | pass |
| large | workflow (5 workers) | 42,727 (+33%) | 152s | pass |

There is no inversion; the opposite happened. For the same passing result, the fan-out engine
spent more tokens at BOTH sizes, and its overhead GREW with breadth (+19% at 2 workers, +33% at
5), because each worker carries its own context cost and the orchestrator pays to integrate.
It was also slower in wall-clock here and wrote more code for the same functional cargo.

## What the suite settles

On a FIXED task, orchestration does not win on per-token efficiency at any size we ran; its
coordination cost scales with fan-out. This confirms, by controlled experiment, the cargo /
scope-vs-efficiency finding (`claims.md`, X6): coordinating an orchestration multiplies token
consumption without a per-token gain. The reason to orchestrate is CARGO, throughput and scope,
work that will not fit one head or spans many independent tasks running in parallel wall-clock,
not thrift. A fixed-cargo dynamometer measures thrift and correctly shows solo winning; it does
not and should not reward throughput. That is exactly why the report reads efficiency and cargo
as separate axes and the recommender conditions on cargo, never ranking on raw efficiency.

## Reproducing it

The comparison is a clean-session artifact, not a one-off: each engine ran as a fresh agent
given only the fixed task and its dispatch directive (solo: do it yourself; workflow: decompose
and fan out), in its own worktree, measured on tokens spent and surviving lines that pass the
check. Any receiver runs the same recipe (`skills/vibrant-dynamometer`) and gets a comparable
table; the numbers move with the task and the models, the method does not.
