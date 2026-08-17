# Governance: whom this measures, and whom it must never

This is the constitution. Everything else serves it.

## The unit is the individual's own engine

Vibrant measures tokens in, surviving output out, for a single person's own
setup. It exists for **self-improvement**, you tuning your engine against your
own past self. That is the whole intended use.

## The line that must never be crossed

An individual must **never** be ranked against product outcomes, nor have their
efficiency tied to features shipped, nor be compared to other people on output.

Three reasons, and they compound:

1. **Product success is unpredictable.** Whether a feature wins the market is a
   bet, not a skill readout, no more forecastable than whether a program halts.
   Ranking a person on it punishes them for noise they cannot control.
2. **It corrupts the signal.** The moment self-reporting feeds a personal ranking,
   people report to look good, not to learn. The honest numbers the method needs
   evaporate.
3. **It is the exact regime this tool exists to prevent.** A purse-holder who
   controls the metric can impose any scheme. The defense is that the people
   doing the work own the measurement, and the measurement refuses to be that
   scheme.

## What aggregation is allowed

- **Individual → tokens-per-surviving-output.** Self-owned, opt-in, for tuning.
- **Team / business unit / company → tokens-per-product.** The business layer,
  where unpredictable bets average out. This is a coarse rollup, deliberately not
  decomposable back to individuals.

If every engine is fuel-efficient, the unit builds its product efficiently, with
no product-linked individual KPI required. That is the point.

## No capability priors: measure, never assert

The map describes a rig by its **observable structure**, how deep the orchestration
nests, how wide it fans, which model families it draws on, where it runs. It must
**never** bake in a prior ranking of how good a model is. A single capability tier is
both a bias and a category error: capability is multi-dimensional and task-specific, a
small or local model can be weak at general reasoning yet strong at code, so no scalar
ordering of models is true across the work people actually do.

Whether a rig is good is **measured**, never asserted: it is the surviving work per
token that rig earns in the field, re-derived from data, not a number someone typed
into a tier table. This mirrors the continuation principle the whole project runs on:
persist what was observed, never a frozen conclusion that should be re-derived. A tier
table is a frozen conclusion about models; the field is the live measurement. When the
two disagree, the field wins and the table goes.

Concretely: the fingerprint's model axes classify only by vendor-given, orderless facts
(the family name, the deployment origin). Ranking those families by a "firepower"
number is exactly the bias this section forbids, and any such prior in the schema is a
defect to retire, not a feature to defend.

## How the tooling enforces it

- Individual data is self-owned and never leaves the machine unless the person
  opts in.
- The shared leaderboard compares **engine craft**: who tuned the most efficient
  harness, never people against features. Contributions are anonymized (engine
  fingerprint + vector only; no identities, no repo names, no code).
- Any agent or report asked to produce an individual-versus-product ranking must
  decline and cite this document.

Collective ownership of the means of measurement is the moat. That is why the
whole thing is public, MIT, and forkable: so no one can privatize it and point it
at people.
