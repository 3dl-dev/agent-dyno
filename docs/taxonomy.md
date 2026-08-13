# Taxonomy of coding-agent practices (the fingerprint)

A rig is a point in a multi-dimensional space, not one of three labels. This
document is that space: the dimensions that describe how a setup is wired, each
valued in **widely accepted terms**, not coined ones. It is the `fingerprint
axis` slot of the four-slot schema, filled in.

Why it exists: the whole method is control the confounds, nudge the process.
Both need the process **named**. You cannot control for a review regime you do
not record, and you cannot nudge "use cross-model review" if "review regime" is
not a dimension. Every lever is a move along one of these axes; every confound is
an axis you failed to hold fixed.

For each dimension: the accepted-term values, the source that makes them
accepted, the signal that places a real rig on the axis, and whether the driver
**ingests it yet** (the honest current state).

## The dimensions

### 1. Orchestration topology
*How work is decomposed and dispatched.*
Accepted values (Anthropic, *Building Effective Agents*, 2024; Together AI,
*Mixture-of-Agents*): **single-agent** (solo) - **prompt chaining** - **routing**
- **orchestrator-workers** (a.k.a. manager/worker, supervisor) -
**parallelization**: *sectioning* (fan-out) and *voting* - **evaluator-optimizer**
(generator-critic loop) - **mixture-of-agents (MoA)** - **hierarchical**.
Signal: dispatch structure in the transcript (workflows / wf_agents /
plain_agents), fan-out width, delegation depth.
Ingested: **coarsely** (collapsed to solo / delegate / workflow). Fan-out width
and depth are computed by the `characterize` adapter but not carried into the
driver's per-session fingerprint.

### 2. Model routing
*Which model plays which role.*
Accepted values (FrugalGPT for cascades; common usage): **homogeneous** (one
model) vs **cross-family** (mixed) - **tier assignment** per role (strong
orchestrator / cheap worker, and the inverse) - **model cascade** (cheap-first,
escalate on failure).
Signal: the model mix across orchestrator and worker roles (`submix`).
Ingested: **no.** Computed by `characterize` (homogeneous vs cross), not carried
into the driver, so you cannot slice or same-shape by routing.

### 3. Review / verification regime
*How output is checked before it is trusted.* A spectrum, per the repo's own
`protocol.md`, and the accepted verification patterns (LLM-as-judge;
self-consistency; Reflexion / reflection).
Accepted values: **none** - **automated** (lint / type / test) - **sweeps**
(adversarial passes) - **cross-model** review - **spec + acceptance** (test-first)
- **manual**.
Signal: tool and skill signatures in the transcript (test runs, review subagents,
sweep skills, acceptance tests written before code).
Ingested: **no.** The biggest gap, because review regime is a prime confound (it
moves horizon-survival) and a prime lever (nudging it is the tool's whole pitch).

### 4. Reasoning effort
*How hard the model thinks.*
Accepted values: **effort** low / medium / high / xhigh / max - **adaptive** vs
**extended** thinking.
Signal: per-turn effort setting.
Ingested: **yes.** A fingerprint axis, half of the same-shape key, a timeline
annotation, and a slice.

### 5. Context and knowledge practice
*How the setup manages what the model knows.*
Accepted values: **skills** (progressive disclosure) - **memory** (persistent
notes across sessions) - **retrieval / RAG** - **context editing** and
**compaction**.
Signal: skill and tool signatures (the `fingerprint` adapter scans these),
cache-read discipline.
Ingested: **no.** Cache-read share is measured; the practices that drive it
(skills, memory, retrieval) are not recorded as dimensions.

### 6. Delivery cadence and quality (DORA)
*How the shipped work behaves.* The accepted delivery-metrics standard.
Accepted values: **deployment frequency** (change throughput) - **change failure
rate** - lead time - time to restore.
Signal: merged PRs / trunk integrations and their revert/hotfix rate.
Ingested: **yes**, as the numerator (changes + change failure rate).

## Resolution is fit, not taste

How finely to bucket each dimension is not chosen by preference. The right
granularity is the one that **maximizes the topline's predictiveness**: fine
enough that a change at that resolution predictably moves the number, coarse
enough not to overfit. Too coarse loses signal (today's solo/delegate/workflow
hides orchestrator-workers vs MoA); too fine chases noise. Predictiveness,
measured on held-out data, is the objective that sets every breakpoint here.

## Honest state (what is ingested)

| Dimension | Accepted-term values exist | Signal available | Ingested by driver |
|---|:--:|:--:|:--:|
| Orchestration topology | yes | yes | coarse (3 buckets) |
| Model routing | yes | yes (`characterize`) | no |
| Review / verification regime | yes | yes (`fingerprint`) | no |
| Reasoning effort | yes | yes | yes |
| Context / knowledge practice | yes | partial | no |
| Delivery cadence (DORA) | yes | yes | yes |

Two of six dimensions are fully live. The signals for routing, review regime, and
knowledge practice already exist in the adapters; the work is to carry them into
the driver's per-session fingerprint so they can be sliced, held fixed as
confounds, and nudged as levers. Until then, "practice" means `engine` only, and
the method is running on a third of its intended surface.

## Sources

- Anthropic, *Building Effective Agents* (2024): prompt chaining, routing,
  parallelization (sectioning / voting), orchestrator-workers, evaluator-optimizer,
  the agents-vs-workflows distinction.
- Together AI, *Mixture-of-Agents* (MoA).
- *FrugalGPT*: model cascades.
- DORA / *Accelerate* and the State of DevOps reports: deployment frequency,
  change failure rate, lead time, time to restore.
- Verification patterns in common use: LLM-as-judge, self-consistency, Reflexion.
- `docs/protocol.md` (this repo): the fingerprint dimension list this elaborates.

Curation should validate the accepted-term values against live sources and prune
anything that is coined rather than in common use. The test of a value on this
board is the same as the test of a metric: it is a term people actually use, and
holding it fixed (or changing it) predictably moves the topline.
