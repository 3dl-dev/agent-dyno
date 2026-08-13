# Roadmap and handoff: completing the fingerprint and the join

A clean session resumes from here. This is an execution pointer, not a belief:
read it, read `skills/dyno-report/dyno_report.spec.md`, run the two tests to
confirm the baseline is green, then execute items 1-5 in order. Do not
re-litigate the decisions logged below; they were made deliberately.

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

## The plan: items 1-5

Do them in order. Each is source-first: write/adjust the spec and the acceptance
test first, then the code.

### 1. Wire the LLM classifier as a cached fingerprint layer
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
Outcome: the topline denominator scopes to the measured repos' own sessions
(kills the window-approx), and complexity/DORA-changes slice by model/effort.
How: use `core/horizon_attribute.py` to attribute commits -> sessions -> model.
Then (a) topline tokens = output tokens of sessions matching the repos; (b) add
`numerator` work units per model/effort. Acceptance: fixture repo + fixture
sessions with matching `proj` -> topline uses only matched sessions' output;
per-model complexity present.

### 3. Extend the slicer
Outcome: `report.html` selector also cuts by effort / engine / routing (not just
model), and the git-side work units (changes, complexity) join the panels.
How: generalize the selector in `render_small_multiples` over the existing
`by_effort/by_engine/by_routing`; add work-unit panels once item 2 lands.
Acceptance: html carries selectors for each dimension; still self-contained;
byte-identical across hash seeds.

### 4. Close the loose ends
Outcome: `confounds()` also names effort-mix, review-regime, and non-overlapping
fuel/git-window confounds; the lever no longer mislabels a `$/survKB` prediction
as a topline move. How: extend `confounds()`; either rehook `best_lever` to
predict the functionality/output headline (needs frontier entries carrying the new
unit) or relabel its fields as an engine-efficiency-vector prediction (depth) and
keep the measure loop as the ground truth on the headline. Acceptance: test asserts
the new confound strings when the conditions hold; lever fields are honestly named.

### 5. Hoist config
Outcome: dyno-report ships itself -- a `hoist` formula (see `~/projects/hoistable`)
that, on install, clones the repo, builds the snapshot, and runs the report with
zero setup. How: author the Layer 2 config per hoistable's model. Acceptance: a
clean machine can `hoist` agent-dyno to a rendered report without manual steps.

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
