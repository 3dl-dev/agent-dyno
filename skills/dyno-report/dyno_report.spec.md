# spec: dyno_report (the turn-key driver)

The one-shot driver behind the `dyno-report` skill. Its reason to exist: the
report must be **accurate and identical whatever model or harness runs the
skill**. An LLM assembling the pipeline by hand cannot promise that; a
deterministic driver can. The model does zero computation. It reads governance,
invokes this driver, and narrates the bundle the driver returns.

## Interface

```
dyno_report --harness <name> --repos <path>[,<path>...] [--since <git-approxidate>]
            [--snapshot <dir>] [--frontier <path>] --out <dir>
```

- `--harness` selects the adapter (claude-code built; pi/opencode are slots). The
  driver calls only the adapter's declared entry points, never harness internals.
- `--snapshot` reuses an existing fuel snapshot; absent, the driver builds one via
  the adapter, then reuses it. Building is idempotent.
- `--frontier` is the commons to compare against; absent, uses the repo's
  `frontier/reference-frontier.json`.
- Reads only local git + local transcripts + the frontier file. No network. No
  state outside `--out`.

## Method (deterministic pipeline; every step is code, none is model judgement)

1. **Fuel.** Ensure a snapshot exists (build or reuse). Load per-session fuel,
   fingerprint, and same-session survival via the adapter.
2. **Numerator.** Run `survival_git` over each `--repos` entry for `--since`.
3. **Join.** Attribute git survival to sessions by engine/model/effort
   (`horizon_attribute`) for every repo that matches sessions.
4. **Vector.** Compute the protocol vector per (engine) and per (engine, model) at
   fixed engine: `$/survKB`, `survKB/out-Mtok`, `waste%`, `human-touches/survKB`,
   `cache-read%`, `orch-tok/survKB`. No composite. Pareto flag only.
5. **Same-shape comparison (the capstone).** For each of the operator's cells,
   match frontier entries of the **same shape**: same engine, same effort tier,
   same model-role tier. Report the operator's vector beside the same-shape
   frontier distribution (min / median / operator-percentile), and the single
   nearest-shape entry whose technique would move the operator's worst axis. If no
   same-shape entry exists, say so explicitly; never compare across shapes.
6. **Claim verdicts.** Re-evaluate each `docs/claims.md` row the run has data for,
   emitting {claim, metric value, verdict}.
7. **Confounds.** Emit named confounds mechanically: horizon age of the window,
   bulk-import repos (single-commit or >Xk-line commits flagged as terrain),
   cells with N below a floor, an **effort mix** across the sessions (the blended
   topline can move on an effort shift, not an engine change), a **review-regime
   mix** or an uncontrolled (unclassified) review regime (a prime survival
   confound), and **non-overlapping fuel/git windows** (fuel sessions and the git
   numerator window covering different periods, so the ratio divides work and fuel
   from different times).

## The functional surface: one number, one lever, a measurable delta

The user sees three things and nothing else:

1. **The topline EQ.** `surviving functionality per Mtok output` -- surviving
   complexity (git decision points, a functionality proxy) over **output tokens**
   (what the model generated). Output, not total tokens: total is ~97% cache-reads
   that drown the signal and are near-free on a subscription; output is the scarce
   generative fuel, and dividing by it penalizes verbosity. **Larger is better**
   (the high-score instinct), unbounded, a ratio so volume cannot game it, and
   burning output for no lasting functionality lowers it (naive tokenmaxxing
   inverted). DORA change failure rate rides alongside as the delivery-quality
   lens; surviving-KB, dollars, and total-token fuel are depth lenses. The seam
   between git-side functionality and session-side tokens is closed by the
   git<->session join: the output-token denominator is scoped to the sessions that
   actually worked in the measured repos (a session matches a repo when the repo
   name is in its `proj`), so the denominator counts only the fuel that bought the
   functionality in the numerator. `topline.denominator_sessions` records how many
   sessions fed it. When no session carries `proj` (older snapshots), the driver
   falls back to the whole-window denominator and the number is a window-approx.
2. **One lever.** The single fingerprint tweak with the largest predicted gain:
   the operator's worst same-shape cell versus the same-shape frontier entry that
   beats it. Reported as a plain tweak (the frontier entry's technique) plus a
   predicted move on the **engine-efficiency vector** (surviving-KB per dollar),
   recomputed as if that cell ran at the frontier entry's efficiency. This
   prediction is honestly a *depth* number in the frontier's own unit (survKB/$),
   **not** the topline headline (functionality per Mtok output): the frontier does
   not yet carry the headline unit, so the lever cannot predict it directly, and
   its fields say so (`unit`, `predicts`). The ground truth on the headline is the
   measure loop below, not this prediction. If no same-shape entry beats the
   operator, there is no lever; say so, never invent one.
3. **Measure.** With `--baseline <prev report.json>`, show the actual topline move
   since last run (the ground truth on the headline). The lever's prior prediction
   is carried alongside but explicitly named as a survKB/$ engine-efficiency move,
   a different unit from the headline delta, so the two are never silently equated.
   This closes the predict-then-measure loop: tweak the rig, re-run, see if the
   number moved.
3b. **The babysitting index.** Turn quality has an objective half that needs no
   inference: how often you had to intervene rather than get clean value, as
   interventions per 100 turns (nudges to continue + interrupts + hand-backs that
   end on a needless question). Reported beside the topline and per week on the
   timeline, and deliberately **not** folded into the EQ (pricing your attention
   against tokens is a separate, operator-owned choice). Honest limit: these
   counters do not capture verbosity, jargon, or unrequested work; the *misery*
   half of turn quality (sentiment on your replies, handover quality) is the
   inference layer below, and it can disagree with the babysitting counters.
4. **EQ over time, annotated with the operator's own fingerprint changes.** Bin
   sessions by ISO week, compute the weekly EQ, and detect when the dominant
   fingerprint (engine, orchestrator model, effort) changed week-to-week. Each
   change is a marked flag on the curve, so a move ties to a change the operator
   made, not to noise. Everyone iterates their stack; those changes are the
   confounds, and making them visible on the curve is how you control for them.
   Rendered as a self-contained chart (`report.html`) and a compact textual
   timeline in `report.md`.

## The inference cost gate (turn-quality layer)

The misery/handover classifier (Haiku triage -> Sonnet classify) spends inference,
so it is opt-in above a threshold. Express its cost the way a subscription user
feels it: **tokens per model, and as a ratio to the window's own baseline usage**,
never dollars. E.g. a full-store pass is Haiku + Sonnet tokens totalling a small
fraction of a week's processed tokens (and a few percent of the scarcer weekly
output). Gate opt-in on that ratio (default: ask above ~1% of weekly output), and
after the pass report tokens actually spent against the same baseline. The tool
eats its own dog food: an assessment's inference cost is justified by the savings
it unlocks, and the operator sees the ratio before the spend.

## The fingerprint labels cache (the pattern dimensions)

Three of the six taxonomy dimensions are patterns, not counts: **fine topology**
(orchestrator-workers vs MoA vs evaluator-optimizer, under the coarse
solo/delegate/workflow), **review regime** (none / automated / agentic review pass
/ sweeps / cross-model / spec+acceptance / manual), and **knowledge practice**
(skills / memory / retrieval / compaction). They do not fall out of a counter, so
the driver does not classify them; the in-session model does, once, and writes the
result to a cache the driver then consumes deterministically. This keeps the
driver a pure function (the determinism invariant) while still filling the axes.

The cache is `fingerprint-labels.json` (default: alongside the snapshot), schema
`agent-dyno/fingerprint-labels@1`:

```
{ "schema": "agent-dyno/fingerprint-labels@1",
  "rigs": { "<rig-key>": { "fine_topology": "...", "review_regime": "...",
                            "knowledge_practice": "..." }, ... } }
```

The **rig key** is the deterministic fingerprint tuple `engine/routing/effort`
(the skeleton the driver already computes per session). Classifying by rig, not by
session, is the dedup decision (roadmap decision 3): every session sharing a
skeleton is one rig, classified once. Labels only, no raw transcript text; the
operator may hand-correct any value. The driver:

- joins each session to its rig key and attaches the three labels (absent cache or
  absent rig -> the label is `unclassified`, and the pending-classification slot
  stays, so a run with no cache is unchanged);
- fills the three pending slots of `fingerprint` from the modal label;
- exposes `fuel_and_work.by_review_regime` (and `by_knowledge_practice`) as
  first-class slices, so review regime can be watched and held fixed like any
  other dimension;
- carries the per-session labels into the confound machinery, so an uneven
  review-regime mix is namable as a confound (see the confounds section).

The evidence the classifier reads is packaged by the adapter (harness-specific),
not the driver: `adapters/<harness>/fingerprint_evidence.py` buckets per-rig
evidence (skills invoked, Bash-command tags of test/lint vs shell, per-subagent
task descriptions) so the model classifies from a compact bundle, never raw logs.
The skill (`SKILL.md`) runs the Haiku->Sonnet cascade over the distinct rigs and
writes the cache; cost is gated exactly like the misery layer above. None of this
is on the driver's critical path: the driver reads the cache if present and is
otherwise unchanged.

Everything else (the full vector, per-cell same-shape, claims, confounds,
numerator, fingerprint, provenance) is machinery. It lives in `report.json` for
inspection, and is kept OUT of the default surface.

## Output

Three artifacts under `--out`, all a pure function of inputs:

- `report.json`: the full structured bundle (topline, lever, measure, timeline,
  vector, same-shape, claim verdicts, confounds, numerator, provenance). The
  contract other tools consume, and the inspect layer.
- `report.md`: the functional surface only, from a fixed template, no model in
  the loop: the topline number, the one lever with its predicted delta, the
  measure line, and a compact annotated timeline. Short by design.
- `report.html`: a self-contained, theme-aware page with two charts. (1) EQ over
  time annotated with the operator's fingerprint changes. (2) **Fuel and work over
  time** as aligned small multiples: the three token streams (cache-read, read,
  output) and the net code retained, each on its own scale, sharing one time axis
  at the `--granularity` bucket (day / week / month). Different scales by design,
  so never one axis (the dataviz method forbids dual-axis). Direct value labels,
  native SVG tooltips. No external assets: any interactivity is inline (a small
  self-contained `<script>`), so the page stays a single hoistable file. A single
  selector cuts the fuel-and-work series by every fingerprint dimension the driver
  slices (model / effort / engine / routing / review regime / knowledge practice),
  grouped so each dimension is its own option group; slices with fewer than two
  non-empty buckets are dropped. Beneath it, the git<->session attribution (per
  model and per effort: surviving lines, surviving complexity, commits) is rendered
  as a compact table, not forced into the time-series panels (it is not a time
  series). Hourly granularity (needs per-turn timestamps) is the next increment.

## Governance (enforced in code, not left to the narrator)

The driver refuses to emit any individual-versus-product or person-versus-person
comparison, and stamps `report.json` with a governance-clean assertion. Same-shape
comparison is engine-craft only (engine x tier x effort), never identities, repo
names, or product outcomes. Cite `docs/governance.md` on refusal.

## Determinism and portability

Output is a pure function of (transcripts in window, git state at HEAD of each
repo, frontier file, current date, adapter version). Same inputs, same day, same
bytes, on any model that invokes the driver. Cross-harness parity is the adapter
contract's job: two harnesses with equivalent work must yield comparable vectors.

## The git<->session join (exact topline + per-model work units)

`horizon_attribute` matches a commit to the session that produced it (same
project, commit time inside the session's active window, short tail tolerance) and
carries that session's model / effort fingerprint. The driver leverages it (never
hand-rolling the project-name match) for two things:

1. **Exact topline.** The output-token denominator is scoped to the sessions whose
   `proj` names a measured repo, so the topline is functionality-in-these-repos
   over the-fuel-that-bought-it, not over the whole window. See the topline
   section; `topline.denominator_sessions` reports the scoped count.
2. **Per-model / per-effort work units.** Surviving lines and surviving complexity
   are attributed to the model and effort that authored them, under
   `numerator.attribution` (`by_model`, `by_effort`, plus `matched` / `unmatched`
   commit counts). This is the durable "whose committed logic lasted" cut, joined
   deterministically (commit timestamps at HEAD, session timestamps in the
   snapshot). A commit whose time matches no session is counted as `unmatched`,
   never silently dropped.

## The numerator's two units (volume and throughput)

Surviving work is reported two ways, because they carry different signal:

- **Surviving KB** (`survival_git`): code volume that lasts. A crude size proxy.
- **Net complexity retained** (`survival_git`, decision-point count over surviving
  code): a language-agnostic cyclomatic-complexity proxy that scales change by
  density, not line count, so a dense change outweighs boilerplate of the same
  size. Crude by necessity (stdlib, no per-language parser; miscounts in strings
  and comments), a companion to volume and never a value measure. The useful cut
  is density (decision points per 1k surviving lines): it separates dense logic
  from bulk that inflates net-KB.
- **DORA changes** (`survival_git.changes`): the accepted delivery vocabulary. A
  *change* is a shipped unit of work (a merged PR), NOT a commit (an arbitrary
  checkpoint). Throughput is deployment frequency; quality is *change failure
  rate* (the share reverted/hotfixed, which our survival signal already
  measures). Source order: the forge (merged PRs via `gh`, the faithful unit),
  then git trunk integrations (first-parent, a labeled approximation that
  degrades to commits when work lands straight on the trunk). Value is
  unpredictable, so the goal is more changes shipped per dollar without raising
  the failure rate, never a size- or value-weighted score.

## Acceptance

`test_dyno_report.py` builds a fixture: a synthetic snapshot (a few sessions
across solo/delegate/workflow at known tokens and known born/killed chars), a
throwaway git repo whose commits map to those sessions, and a fixture frontier
with one same-shape and one different-shape entry. It runs `dyno_report` and
asserts:

1. the per-engine vector equals hand-computed values;
2. the same-shape comparison matches only the same-shape frontier entry, and
   states "no same-shape entry" for a cell that has none;
3. `report.json` carries full provenance and the governance-clean stamp;
4. a second run on the same fixture and date is byte-identical;
5. the topline denominator counts only the sessions whose `proj` names the
   measured repo (a non-matching session's output is excluded), and
   `numerator.attribution.by_model` carries the surviving complexity attributed to
   the model whose session window brackets the fixture commits;
6. supplying a `fingerprint-labels.json` cache fills the three pattern fingerprint
   dimensions and exposes a `by_review_regime` slice.

A build that does not pass this is not a valid build. The skill may not ship a
number this driver did not produce.
```
