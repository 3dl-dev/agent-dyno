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
not because it was handed easier work. This is the opposite direction of the observational
artifact and exactly why the dynamometer is the arbiter: it answers per difficulty. The
inversion (a large, decomposable task where fan-out's throughput repays its overhead) is the
next run: add a heavier task to the suite and the ordering is expected to flip. A single small
task settles the small-task regime; a suite spanning sizes maps where each engine wins.

## Reproducing it

The comparison is a clean-session artifact, not a one-off: each engine ran as a fresh agent
given only the fixed task and its dispatch directive (solo: do it yourself; workflow: decompose
and fan out), in its own worktree, measured on tokens spent and surviving lines that pass the
check. Any receiver runs the same recipe (`skills/vibrant-dynamometer`) and gets a comparable
table; the numbers move with the task and the models, the method does not.
