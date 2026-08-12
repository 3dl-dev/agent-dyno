# Operating Agent Dyno (for agents)

This repo is run by agents as much as by people. If you are an agent asked to
measure a setup's efficiency, this is your map. Read `docs/governance.md` first, 
it is a hard constraint on what you may report, not a preference.

## The invariant you must not break

You measure an **individual's own engine**: tokens in, surviving output out, for
self-improvement. You must **never** rank an individual against product outcomes,
tie their efficiency to features shipped, or compare people on output. Product
success is an unpredictable bet; ranking a person on it is surveillance, and it
poisons the honest self-reporting the whole method needs. If asked to do this,
decline and roll the measurement up to team/BU for tokens-per-product instead.

## What to run

- **Objective numerator, any repo, any agent**: `core/survival_git.py`. Reads
  git only, so it is harness-neutral. Start here; it needs no adapter.
- **Full report from a specific harness**: pick the adapter under `adapters/`
  (claude-code is built; pi and opencode are slots). Each adapter normalizes that
  harness's logs into the common schema, then the analyses run.
- **Self-contained method**: every skill under `skills/` carries its full method
  in the SKILL.md. You can execute it cold, stdlib only, nothing to install.

## What to report

The efficiency **vector**, never a single score (a composite built from volume
re-flatters the worst engine). Every number is `f(model, harness, effort,
review, interaction)`; report the terms and name the confounds (terrain,
non-overlapping windows, effort mix, small N). Survival is not the same as value; say so.

## How to extend

- A new harness → a new `adapters/<name>/` that emits the common schema. Do not
  fork the analyses.
- A new model → add it to the price registry (`adapters/claude-code/prices.json`
  shape), never hardcode an ID.
- A new dimension → it lands in exactly one existing slot: a fingerprint axis, a
  fuel line, a horizon on the numerator, or a claim row. If it needs a fifth
  slot, stop and rethink; that is the signal you are accreting, not converging.
