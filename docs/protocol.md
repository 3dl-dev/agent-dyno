# The Agent Dyno protocol

Read [governance.md](governance.md) first. This document is the method.

## Tokens are fuel, the harness is the engine, work is what survives

Efficiency is **surviving work per token**. It is intrinsic to the run,
measurable after the fact, and needs no prediction of what wins the market.

| term | concretely |
|---|---|
| fuel | tokens, priced in dollars (input / output / cache-write / cache-read differ ~20×) |
| engine | the harness: model routing, delegation topology, review regime, effort |
| work | code that **survives** in git, not reverted, not rebuilt, not later bug-fixed |
| efficiency | surviving work ÷ fuel, reported as a **vector**, never one score |

A composite score is the Goodhart door: fold survival into a volume-heavy index
and the worst engine still ranks first. Report the vector; the frontier is
Pareto, not a ranking.

## The numerator: survival at a horizon

Raw lines-written is volume, not work. The unit of shippable work is code that
**lasts**. Measured from git, at increasing horizons (session → day → week):

- **immediate withdrawal** → dies same session.
- **rebuild** → churned; no longer blamed to the adding commit.
- **defect** → a later bug-fix lands on the lines, proving they were not shippable.

Because this is a git property, it is **harness-neutral**: a human, Claude Code,
pi, or OpenCode are all measured identically. `core/survival_git.py` computes it.

## Retention: git plus a tiny snapshot, no infrastructure

Long-horizon analytics needs the past, but almost none of it needs archiving:

- **The numerator is already retained: by git.** Which lines you added survive
  is in your history forever, for everyone, free. No archiver, no NAS, no tank.
- **Only the fuel/fingerprint side rotates** (transcripts, ~30 days). Retain it
  with `adapters/<harness>/snapshot.py`: a periodic dump of the *derived*
  per-session metrics, kilobytes a month, local. The full history of one
  operator's setup is ~3.5 MB, against ~2.8 GB of raw transcripts.

So retention here is universal: **keep git (you already do) plus these tiny local
snapshots.** Shipping raw transcripts to a NAS / tank / S3 is an optional backend
for recomputing new metrics over old windows; it is not required and not part of
this kit. Do not assume anyone else has your storage.

## Rigor and review are measured, not mandated

Skipping review looks hyper-efficient in the short run because it spends no
tokens verifying. But the cost was moved, not removed, onto a human (manual
review) or onto the future (defects at horizon). A framework that tracks both
fuel lines (tokens **and** human attention) plus horizon-survival sees where it
went. So review is a first-class fingerprint axis, a spectrum, not an ideology:
none → automated → sweeps → cross-model → spec+acceptance → manual. You do not
mandate a regime; you let horizon-survival say which one paid.

## The efficiency vector

Per group (engine, and model at fixed engine), all reported together:

`$/surviving-KB` · `surviving-KB per output-Mtok` · `waste %` ·
`human touches per surviving-KB` · `cache-read share` ·
`orchestrator-tokens per surviving-KB`.

## The fingerprint: naming the engine

Topology (fan-out width, depth), delegation share, model routing (homogeneous vs
cross-family), parasitic load, cache discipline, review regime, effort. This is
what lets you say *which engine* produced a number instead of guessing from the
model label.

## The four-slot schema

Everything new lands in exactly one slot, or the design has lost its way:

1. a **fingerprint axis** (review regime, topology, routing),
2. a **fuel line** (tokens; human attention),
3. a **horizon** on the numerator (session → day → week),
4. a **claim to adjudicate** ([claims.md](claims.md)).

A dimension that needs a fifth slot is a signal to stop and rethink.
