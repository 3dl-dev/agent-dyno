# Roadmap and handoff: completing the fingerprint and the join

A clean session resumes from here. This is an execution pointer, not a belief:
read it, read `skills/dyno-report/dyno_report.spec.md`, run the tests to confirm
the baseline is green. Do not re-litigate the decisions logged below; they were
made deliberately.

**Items 1-5 are complete** (branch `dyno-report-driver`, commits `2937ed0`
through `fa2142e`); see the per-item DONE notes under "The plan" below. To confirm
the baseline, run every test:

```
python3 core/test_survival_git.py
python3 skills/dyno-report/test_dyno_report.py
python3 adapters/claude-code/fingerprint_evidence.py --selftest
python3 skills/dyno-report/demo.py --selftest
```

Branch: `dyno-report-driver`. Baseline is committed and green.

```
python3 core/test_survival_git.py
python3 skills/dyno-report/test_dyno_report.py
# run the real report:
python3 adapters/claude-code/snapshot.py --out /tmp/dyno
python3 skills/dyno-report/dyno_report.py --harness claude-code \
    --snapshot $(ls -d /tmp/dyno/*/ | tail -1) \
    --repos <comma-separated repos you code in> --since 30.days.ago --out /tmp/rep
```

## The regime (tokenmaxxing 2.0)

Maximize durable *shipped* work per unit of total fuel (tokens **and** the
operator's attention), and take more shots per dollar; found by tuning the rig,
proven by predict-then-measure. Not "spend fewer tokens" (that is 1.0, and it is a
trap: value is unpredictable, so you want more good attempts, not thrift).

The whole product is **one pipe**: clean session -> skill (read governance, run
driver, narrate) -> deterministic driver reads local logs + git -> `report.json`
(the whole truth, byte-identical on any model) -> surface = **one number** + one
lever + one measurable delta, plus charts -> tweak the rig -> re-run `--baseline`
-> it says whether the number moved. Everything is more data flowing through that
same pipe. The surface stays one number; everything else is depth you descend into.

## Invariants (never violate)

- **Stdlib only.** No installs, no dependencies. Verify: no `pip`, no imports
  outside the stdlib + repo modules.
- **The model computes nothing in the driver.** The Python driver is a pure,
  deterministic function; that is what makes `report.json` byte-identical across
  models (the trust). LLM work happens in a separate cached layer whose labels the
  driver merely consumes.
- **Determinism.** `report.json` and `report.html` are byte-identical across
  `PYTHONHASHSEED`. The acceptance test enforces this; keep it.
- **Harness-neutral.** The numerator is git (harness-agnostic). Fuel is per-harness
  behind a thin adapter. New code reads generic fields, not Claude-Code specifics.
- **Hoistable / ships-itself.** Self-contained, zero-setup. Inference runs via the
  *in-session model* (no API keys, no installs). `report.html` has no external
  assets.
- **One-number surface.** `report.md` is the number + the lever + the measure line.
  Everything else lives in `report.json` (data) and `report.html` (charts). Do not
  accrete companion lines onto the surface.
- **No em-dashes.** Anywhere. Verify: `grep -rnP '\x{2014}' skills core docs`.
- **Source first.** A behavior change is a spec change plus an acceptance-test
  change first; code follows and must pass the test. See `SOURCE.md`.
- **Governance / no composite.** The topline is a genuine ratio (work / fuel), not
  a weighted index; the full vector still lives one layer down. Never rank a person
  against product; engine-craft only. See `docs/governance.md`.
- **Four-slot schema.** Every new dimension lands in exactly one slot: fingerprint
  axis, fuel line, a horizon on the numerator, or a claim row. A fifth slot means
  stop and rethink.

## Current state (what is built)

- **Topline** = `surviving functionality per Mtok output`, LARGER is better.
  Functionality = surviving complexity (git decision points, a functionality
  proxy). Denominator = output tokens (the scarce generative fuel; total tokens are
  ~97% cache-reads that drown the signal; output also penalizes verbosity). DORA
  change failure rate rides alongside. `topline()` in the driver.
- **Numerator, three units** (`core/survival_git.py`): surviving KB (volume), DORA
  `changes()` (merged PRs via `gh`, git-trunk fallback labeled approx) + change
  failure rate, and `net_complexity` (decision-point proxy for change magnitude).
- **Turn-quality, objective half:** babysitting index (nudges + interrupts +
  hand-backs on a question, per 100 turns). In `report.json`, timeline-annotated.
- **Turn-quality, inference half (misery/handover):** PROVEN on real data with a
  Sonnet subagent, cost-modeled in tokens + ratio-to-weekly (~14.5M tokens =
  ~0.23% of a week for a full-store pass). NOT integrated into the pipe. This is
  item 1's sibling; same layer shape.
- **Fuel-and-work chart** (`report.html`): cache-read / read / output tokens + net
  code retained, aligned small multiples (different scales, so no dual-axis).
  Interactive **model selector** (self-contained JS). Sliced data in
  `report.json.fuel_and_work.by_model / by_effort / by_engine / by_routing`.
- **Fingerprint (the taxonomy operationalized):** `docs/taxonomy.md` defines the
  rig as a point in six accepted-term dimensions. `fingerprint_summary()` places
  the run's dominant rig on all six. Live dimensions: topology (coarse) + fan-out
  width, model routing, effort, delivery cadence. Pending (LLM): fine topology,
  review regime, knowledge practice.
- **Same-shape frontier comparison, lever, measure loop, claim verdicts,
  confounds, provenance** all in `report.json`.

## Key decision log (do not re-open)

1. Topline is **functionality per Mtok output**, larger better. Reasons: cost
   framing (`$/survKB`) is smaller-better and backwards; total tokens are
   cache-read-dominated (unintuitive 0.19); output is the scarce generative fuel
   and penalizes verbosity (59.78 is legible). Read: ~17k output tokens per
   surviving decision point.
2. Work numerator combines **DORA + complexity**: functionality (complexity) =
   *what* you built; DORA (change failure rate) = *how well* you shipped it.
   Merges/commits as a *scope* unit are rejected (arbitrary checkpoints); DORA's
   *quality* half is kept. Complexity is a proxy for functionality, crude
   (stdlib, no parser), a companion to volume, never a value measure.
3. The fingerprint is **LLM-classified against the taxonomy, with deterministic
   evidence**. Countable dims (routing) stay deterministic; pattern dims (fine
   topology, review regime, knowledge practice) go to the classifier because it
   generalizes from partial/novel evidence. Cascade: Haiku triage -> Sonnet ->
   Opus if needed. Classify distinct *rigs*, not sessions (dedup); ~40k tokens / 4
   rigs, a fraction of a percent of weekly output.
4. Inference cost is expressed in **tokens per model and as a ratio to the
   window's own baseline usage**, never dollars (subscriptions). Opt-in above a
   threshold (default ~1% of weekly output).
5. The **git<->session join** is the shared unlock: it makes the topline exact
   (scope tokens to the measured repos' sessions) and lets the git-side work units
   (complexity, changes) be sliced by model/effort. `core/horizon_attribute.py`
   already matches commits to sessions by project + time; leverage it, do not
   hand-roll project-name matching.

## The plan: items 1-5 (DONE)

All five landed source-first (spec + acceptance test first, then code), each its
own commit on `dyno-report-driver`. The per-item outcomes below are kept as the
record of what was built; the "DONE" line on each says where it lives.

### 1. Wire the LLM classifier as a cached fingerprint layer
**DONE** (`2937ed0`). Driver: `rig_key` / `load_labels` / `attach_labels`;
`fingerprint_summary` reads the modal rig label or keeps the pending slot;
`by_review_regime` + `by_knowledge_practice` slices; `--labels` flag with default
discovery alongside the snapshot. Adapter: `adapters/claude-code/fingerprint_evidence.py`
(per-rig evidence, `--selftest`). Skill: `SKILL.md` step 3b runs the cascade and
writes `fingerprint-labels.json`. Test: fixture cache fills the pattern dims + a
`by_review_regime` slice appears + byte-identical across seeds.
Outcome: the three pending fingerprint dimensions (fine topology, review regime,
knowledge practice) are filled per rig by the in-session model and consumed by the
driver as real dimensions (sliceable, holdable-as-confound, nudgeable-as-lever).
How: (a) a stdlib evidence extractor that packages per-rig evidence, enriched with
the two signals the classifier itself asked for -- per-subagent task descriptions
and Bash-command tagging (test/lint vs shell); knowledge-practice via `skills`
invoked (nearly deterministic). (b) the skill instructs the in-session agent to
run the Haiku->Sonnet cascade over *distinct rigs* and write
`fingerprint-labels.json` (labels only, no raw text; operator-correctable). (c)
the driver reads that cache and merges labels into `fingerprint_summary` and the
slice/same-shape/confound machinery. Cost-gated per decision 4. Same shape as the
misery layer -- build them together if cheap. Acceptance: fixture labels cache ->
fingerprint dims populated + a `by_review_regime` slice appears; determinism holds
(driver consumes cache deterministically).

### 2. Git-side join (exact topline + per-model work units)
**DONE** (`edadae9`). Topline denominator scopes to sessions whose `proj` names a
measured repo (`topline.denominator_sessions`; window-approx fallback when no
`proj`). `numerator.attribution` (by_model / by_effort, matched / unmatched)
attributes surviving lines + complexity via `attribute_work`, reusing
`horizon_attribute.load_sessions` and `survival_git`. Test: s4's non-matching
`proj` is excluded from the denominator; the fixture commits attribute their 6
decision points to s1's opus-5/high.
Outcome: the topline denominator scopes to the measured repos' own sessions
(kills the window-approx), and complexity/DORA-changes slice by model/effort.
How: use `core/horizon_attribute.py` to attribute commits -> sessions -> model.
Then (a) topline tokens = output tokens of sessions matching the repos; (b) add
`numerator` work units per model/effort. Acceptance: fixture repo + fixture
sessions with matching `proj` -> topline uses only matched sessions' output;
per-model complexity present.

### 3. Extend the slicer
**DONE** (`f9bd8fc`). One `report.html` selector cuts by model / effort / engine /
routing / review-regime / knowledge-practice (optgroup per dimension; slices with
<2 non-empty buckets dropped). The git-side attribution joins the page as a compact
table (`render_attribution`), not a fake time-series panel. Self-contained,
byte-identical across seeds. Test asserts a group per dimension + the table + no
external asset reference.
Outcome: `report.html` selector also cuts by effort / engine / routing (not just
model), and the git-side work units (changes, complexity) join the panels.
How: generalize the selector in `render_small_multiples` over the existing
`by_effort/by_engine/by_routing`; add work-unit panels once item 2 lands.
Acceptance: html carries selectors for each dimension; still self-contained;
byte-identical across hash seeds.

### 4. Close the loose ends
**DONE** (`49d4325`). `confounds()` now also names an effort mix, a review-regime
mix or an uncontrolled (unclassified) review regime, and non-overlapping fuel/git
windows (takes `now`). The lever no longer calls its prediction
`predicted_topline_eq`: it is a survKB/$ engine-efficiency move (`unit`,
`predicts`, `predicted_efficiency[_delta]`), not the headline; the measure loop is
ground truth on the headline and carries the prior prediction under a
different-unit name. `confounds()` unit-tested directly; lever honesty asserted.
Outcome: `confounds()` also names effort-mix, review-regime, and non-overlapping
fuel/git-window confounds; the lever no longer mislabels a `$/survKB` prediction
as a topline move. How: extend `confounds()`; either rehook `best_lever` to
predict the functionality/output headline (needs frontier entries carrying the new
unit) or relabel its fields as an engine-efficiency-vector prediction (depth) and
keep the measure loop as the ground truth on the headline. Acceptance: test asserts
the new confound strings when the conditions hold; lever fields are honestly named.

### 5. Hoist config
**DONE** (`fa2142e`). `skills/dyno-report/demo.py` fabricates a synthetic snapshot
+ throwaway git repo and renders `report.{json,md,html}` with zero setup (exercises
the join, the labels cache, the lever, the slicer; `--selftest`). `hoist/config.json`
is agent-dyno's canonical Layer 2 formula: a hermetic profile whose bringup renders
the demo and whose acceptance re-runs the stdlib self-tests and grades the chart.
Verified end to end: `python3 <hoistable>/hoist/hoist.py <agent-dyno>/hoist/config.json`
-> BUILT, transfer 6/6. NOTE: to hoist by name (`hoist agent-dyno`), repoint the
hoistable index entry to `../agent-dyno/hoist/config.json` (a one-line change left
unapplied to avoid committing to the hoistable repo's main branch, which carried
unrelated in-flight work). Direct-path hoist needs no hoistable change.
Original outcome: dyno-report ships itself -- a `hoist` formula (see
`~/projects/hoistable`) that, on install, clones the repo, builds the snapshot, and
runs the report with zero setup.

## Files map

- `core/survival_git.py` -- numerator: `survival()` (KB), `changes()` (DORA),
  `net_complexity` (decision points). `core/horizon_attribute.py` -- commit<->
  session join (item 2). `core/test_survival_git.py` -- numerator acceptance.
- `skills/dyno-report/dyno_report.py` -- the deterministic driver.
  `test_dyno_report.py` -- the acceptance test (the contract).
  `dyno_report.spec.md` -- source of truth. `SKILL.md` -- the three-step skill.
- `docs/taxonomy.md` -- the fingerprint dimensions in accepted terms.
- `adapters/claude-code/` -- `snapshot.py`, `characterize.py` (routing/fanout
  signals), `fingerprint.py` (skill/tool signatures), `mb_cost.py` (pricing).
- `frontier/reference-frontier.json` -- the commons the same-shape lever reads.

Curation of `docs/taxonomy.md`: validate the accepted-term values against live
sources; the test of a value is that people use the term and holding it fixed (or
changing it) predictably moves the topline. Resolution per dimension is set by
predictiveness, not taste.
