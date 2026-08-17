# Reading the Vibrant report

The report is a single scorecard over your own coding runs: a headline score, three
meters, a timeline of generations, and a learned map of the rigs you actually use. Every
element is a fact about your runs, so nothing on the card is falsifiable or comparative
against anyone else. This guide explains each piece, then lists the external research and
methods the design draws on and the ones it deliberately refuses.

For the philosophy behind the numbers, read `governance.md` (the constitution) and
`protocol.md` (the measurement). This is the operator's-eye view of the rendered card.

## Anatomy, top to bottom

### 1. The score (watch the movement, not the size)

The big number is `efficiency x flow x simplicity`, the three meters multiplied. Its
absolute magnitude is arbitrary on purpose: a score of 2.4M is not "2.4 million" of
anything. It exists so a single line can move up or down as your rig changes. Read the
trend, never the digits. The three components ride along underneath as their own waves so
you can see which one moved the score.

### 2. The three meters (a vector, never one truth)

Efficiency is reported as a vector, never collapsed to one ranking, because the ways a
setup can be good do not reduce to a scalar (`protocol.md`, "the efficiency vector"). The
card surfaces three:

- **efficiency** = durable shipped work per output-Mtok. Surviving work over the fuel
  that produced it. Larger is better.
- **flow** = 100 minus friction (the "misery" of a session: retries, failed edits, dead
  ends). Higher is smoother.
- **simplicity** = a stock measure of the surviving code's complexity DENSITY (decision
  points per 1000 surviving lines), not the inverse of bloat. Higher is simpler. The full
  definition and why density beats `100 - bloat` is in `claims.md`.

Each meter is a toggle: hover to preview its effect on the score, click to hold. They sit
at different scales by design; the score is their product, not their sum.

### 3. The timeline (generations, scrub to hold)

The waveform is your score over time. The colored bands behind it are **generations**: eras
where your prevailing rig held steady, labeled by the surviving work in that era (3M, 970k,
2M). Hovering a bar previews that day into the map below; hovering a band previews that
generation; clicking holds the slice so you can read it, and clicking again releases back to
now. The map's YOU and BEST recompute for whatever slice drives it, so they are never
static: they answer "who were you, and what was best, in THIS window."

### 4. The map (a learned fingerprint, drawn as territory)

The map is a Self-Organizing Map (SOM): an unsupervised Kohonen network that learns a
2-D organization of your sessions from their shape vectors, so similar rigs land in
neighboring cells (`som_train.spec.md`, `rig_space.spec.md`). It is trained out of band and
cached; the report only consumes the cache, deterministically.

It is drawn as a Civilization-style territory map because a strategy map is self-evident in
a way a scatter of dots is not: the engine you ran (solo / delegate / workflow) paints each
cell, and cells of the same engine are fenced with a traced national-style border, so the
regions read as countries at a glance. Cost shades each hex (darker = costlier per surviving
KB). Hover any hex and its full reading floats at the cell: the exact rig, sessions, cost,
and the three meters.

### 5. YOU and BEST

**YOU** is your capital: the cell where your recent WORK concentrates, weighted by output
tokens, not session count (counting sessions over-weights quick solo blips; on real logs
solo is about half the sessions but under a fifth of the work). **BEST** is the rig the
recommender points you to for the metrics you have enabled. Both are drawn client-side for
the current timeline slice, so they move as you scrub.

### 6. The coordination core (the fourth axis)

Inside each cell, a bright teal **core** shows coordination: how much that rig's sibling
workers built on shared files versus siloed into separate ones. A big bright core means the
workers converged on a shared set; a bare dot or nothing means they fanned out and never
touched the same file. SOLO territory is hollow by construction, since a single actor cannot
coordinate.

The core is **neutral**. A bright core is not "better." High overlap can mean genuine
coordination OR two workers fighting over the same file, and only survival disambiguates,
so the field judges the payoff, not the axis. This axis (session-features schema v3) exists
because the research below found coordination QUALITY, not agent count or topology, is what
decides whether more agents help.

### 7. The recommendation and the cargo rule

Below the map, one line names the single change with the largest predicted gain for your
enabled metrics. It is governed by a **cargo rule**: a candidate rig is only offered as an
upgrade if it carries at least half the durable work (cargo) your current cell moves. This
is the fix for the "bicycle problem": pure per-token efficiency always favors the leanest
setup, the way a bicycle is the most efficient way to travel until you need to move a ton of
cargo. Efficiency is roughly flat across engines on real data while total surviving work
varies 4-5x, so the recommender conditions on throughput and never advises a bicycle for a
truck's job. See `claims.md`, row X6.

## The four-slot discipline

Every dimension on the card lands in exactly one of four slots, and a dimension that needs a
fifth is a signal to stop and rethink (`CLAUDE.md`). The slots: a **fingerprint axis** (what
the SOM embeds, including coordination), a **fuel line** (a token stream in the cost
breakdown), a **horizon** on the numerator (session / day / week survival), or a **claim
row** (a hypothesis in the register). Coordination entered as a fingerprint axis; the
multi-agent findings that motivated it entered as claim rows. Neither touched the score.

## What we built on

The design is harness-neutral and self-owned, but it stands on published research and
established method. What we took, and where it lives:

### External research (framed as hypotheses to test, not truths adopted)

- **Anthropic, "Multi-agent systems"** (anthropic.com/research/multiagent-systems). Their
  finding that coordinating an orchestration multiplies token consumption with the payoff in
  SCOPE, not per-token efficiency, is the external corroboration for the cargo rule (the
  bicycle problem) and the motivation for the coordination axis. Captured as claim rows
  X6-X8 in `claims.md`.
- **Anthropic, "Optimizing for cost and intelligence"** (platform.claude.com). Their
  measured findings on model tier, cache hygiene, the flat reasoning-effort curve, and
  tail-concentrated cost are logged as claims X1-X4 in `claims.md`, to verify against your
  own git-survival data rather than adopt.

Both are treated the same way: their benchmark numbers are theirs and will drift; the SHAPE
is what we test on your data. Neither is imported as a result.

### Methods

- **Kohonen Self-Organizing Maps** (T. Kohonen, self-organizing feature maps). The learned
  fingerprint is a batch SOM with a deterministic PCA-oriented init; the lattice size uses
  the **Vesanto heuristic** (`units = 5 * sqrt(N)` nodes). See `som_train.spec.md` and
  `som_train.py`.
- **The Civilization-style territory map.** The engine-territory-with-borders rendering
  borrows the strategy-map convention (bordered nations over terrain) because it makes
  regions self-evident where a raw SOM heatmap is not. See `som_viz.spec.md`.
- **The 3dl brand mark IS a SOM** (3dl.dev/brand): the tall fingerprint shape is the same
  object the tool measures, which is why the default lattice is portrait.

### What we deliberately did NOT take, on principle

- **Model capability by generation** (the multi-agent source's merge-rate-by-model data).
  That is a capability prior, and the constitution forbids asserting capability: survival
  MEASURES it, we never declare it (`governance.md`, "No capability priors: measure, never
  assert"). Coordination is drawn neutral for the same reason.
- **Task shape / parallelizability** ("multi-agent wins on breadth-first work"). That
  measures the task, not the setup; Vibrant stays setup-focused so it survives unseen work.

## Provenance and reproduction

The report is generated by `skills/vibrant-report` from your own logs; the numerator is
retained by git (which lines survived), so a claim on the public frontier can be re-run.
Fingerprint extraction is `adapters/claude-code/session_features.py` (schema
`vibrant/session-features@3`), the SOM is trained by `adapters/claude-code/som_train.py`,
and curation tiers for public contributions are in `CLAUDE.md`. Nothing in the card leaves
your machine unless you contribute an anonymized result.
