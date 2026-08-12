# What "source" means here

This project treats code as a solved, regenerable output, so the source of truth
is not the `.py`. A `.py` file here is a build artifact, the rough equivalent of a
compiled binary: useful, runnable, but downstream of the real thing.

The source of a tool is three parts:

1. **The spec** (`<tool>.spec.md`): what the tool must do. Inputs, outputs, method,
   determinism, and known limits, precise enough that a capable agent can produce
   an implementation from it with no other context.
2. **The generator**: the prompt or method that turns the spec into code. For the
   agent skills, this is the `SKILL.md` itself. For an analysis tool, it is "hand
   the spec to a coding agent and ask for a stdlib-only implementation."
3. **The acceptance test** (`test_<tool>.py`): the spec made executable. It builds
   a fixture with a known answer and checks the implementation against it. This is
   the part that confirms a build does exactly what the spec says.

The checked-in `.py` is a **reference build**: generated from the spec, verified by
the acceptance test, and kept for convenience. You are meant to be able to delete
it, regenerate it from the spec, and have the acceptance test pass. If the spec and
the test agree and the code passes, the code is correct by construction, whoever or
whatever wrote it.

## Why

If the code is the artifact you can rebuild on demand, then publishing only the
code is publishing the binary. The reproducible, forkable, improvable thing is the
spec and the test. That is the open source that survives "code is solved": you can
change the spec, regenerate, and know it still holds, or tighten the test and find
out where the code was lying.

## Contributor rule

A new tool lands as a spec plus an acceptance test first. The reference build comes
after and must pass the test. A change to behavior is a change to the spec and the
test; the `.py` follows.
