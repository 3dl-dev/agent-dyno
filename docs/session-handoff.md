# Vibrant session handoff (2026-08-15)

You are waking from sleep, not being born. This records what was executed and the
situated facts to resume from. Re-derive live conclusions (metric rankings, what the
data says) from current data; do not freeze them. Verify any file/function named here
still exists before relying on it.

## What Vibrant is

Measures the token-efficiency of an AI coding setup from the operator's own logs and
git, harness-neutral, self-owned, federated. Repo `3dl-dev/vibrant`, local
`~/projects/agent-dyno`, branch `dyno-report-driver` (pushes to `main`; not pushed).
The deliverable is a SKILL, not code: it must TRANSFER to a blank agent and do the
right thing, and the only proof is the clean-session transfer test.

## The three meters (the current metric model, load-bearing)

Re-derive the numbers from data; the SHAPE below is the decided design.

- **efficiency = durable shipped CHANGES per Mtok output** (function per fuel). NOT
  complexity. Counting complexity was "the spear": it rewarded over-engineering, so a
  bad model looked efficient. A count of shipped units (non-fix commits) cannot be
  inflated by over-engineering. `topline.eq`, `numerator.durable_changes`.
- **bloat = complexity per shipped change** (`topline.bloat`). The over-engineering
  meter; higher is worse. It is the number that exposes a fake efficiency: opus-5 runs
  ~64 decision points per commit vs opus-4-8's ~33.
- **misery = 0-100** operator friction, from a BLIND LLM classifier over the operator's
  own reply texts (frustration / course-correction / scope / verbosity). Operator-
  relative, NEVER folded into efficiency, never a cross-operator or model verdict. On
  the card and per-era on the timeline. Spec: `misery.spec.md`, test `test_misery.py`,
  cache `misery-cache.json` (schema `vibrant/misery@1`), driver reads via `load_misery`.

All three slice by the fingerprint arms (`_misery_by`, `attribution.by_*`).

## The fingerprint = a trajectory in a collapsed latent space (rig_space)

The fingerprint is NOT categorical bars; it is a POSITION in a continuous low-D space
that MOVES over time. Four axes: three latent (`fan_out`, `firepower`, `rigor`) plus
time.

- Borrowed structure, ATTRIBUTED in `rig_space.spec.md` Acknowledgments: PAD (Mehrabian
  and Russell 1974; Mehrabian 1996) for the continuous-affect space; ALMA (Gebhard
  2005) for the layered dynamics. We reuse the SHAPE, not an affect model; the math is
  general dynamical systems.
- Three bodies at three velocities: session = emotion (fast), era = mood (medium),
  baseline = personality (slow). Update: `pos += response * (target - pos)`.
- Time matters twice: YOUR position moves (you iterate), AND the field moves (a new
  model shifts the optimum; opus-5 did not exist before late July). It is a control
  problem: your trajectory vs the moving frontier.
- HAND-WRITTEN embedding is BUILT and committed (`ca40e81`): `_embed`,
  `_layered_trajectory`, `rig_space()`, `report["rig_space"]`. Test `test_rig_space.py`.
  Real run: personality `[0.35, 0.87, 0.45]`, mood `[0.16, 0.88, 0.41]` (drifted toward
  solo), gradient `[+0.34 fan_out, -0.28 firepower, -0.06 rigor]`.
- NEXT: the LEARNED SOM (see plan below). The hand-written stays as the fallback.

## The recommendation = gradient descent on the true economy

- Objective is DOLLARS per shipped change (not tokens, not complexity). Dollars price
  the orchestrator's cache-read cost (the dominant cost), so it is not fooled by the
  opus-drives-sonnet false economy. Research: `~/projects/dap/docs/specs/harness-
  efficiency-protocol.md` and `.../swarm-dispatch/SKILL.md` ("run the orchestrator at
  sonnet"; opus orchestrator cache reads dominate cost).
- `gradient_move()` descends per fingerprint axis (orchestrator / worker / effort).
  TOPOLOGY IS DELIBERATELY EXCLUDED: delegation buys throughput and scale, so "go solo"
  is never a cost move (the operator builds VMS and other systems via delegation).
- Current recommendation: "Run your orchestrator at sonnet-5 instead of opus-4-8"
  (about 47% cheaper per change, keeps delegating). Rendered as a one-line move plus a
  collapsed `<details>` with the evidence and a copy-paste agent prompt.

## Architecture patterns to follow

- OUT-OF-BAND INFERENCE + CACHE SEAM: expensive or LLM steps (misery, the pattern
  classifier, the future SOM) run out of band (skill or subagent), write a cache; the
  STDLIB driver consumes it deterministically. Keeps the driver a pure function.
- STDLIB-ONLY DRIVER. No numpy in the driver. Out-of-band training may use numpy.
- SOURCE-FIRST: `<tool>.spec.md` + `test_<tool>.py` before code; the code must pass the
  test. See `SOURCE.md`.
- NO EM-DASHES anywhere (docs, comments, commit messages). Verify:
  `grep -rnP '\x{2014}'`. This bit twice this session; check before every commit.
- DETERMINISM: report output is a pure function of inputs; `test_vibrant_report.py`
  asserts byte-identical re-runs.
- Preserve the governance invariant (`docs/governance.md`): measure survival and
  self-improvement, never rank people against product outcomes.

## The shipping loop (memory: skill-distribution-loop)

Every iteration: source-first, UPDATE THE HOIST CONFIG (`hoist/config.json`, just
another build parameter, never a blocking question), compile with hoistable, TRANSFER-
TEST in a CLEAN AGENT SESSION, measure, tweak, repeat. `hoist/config.json` exists and
graded BUILT 2/2. The emitted `hoist/vibrant.hoist.SKILL.md` is gitignored build
output. Toolchain: fetch + verify sha256 + unpack (pin lives in the hoistable skill).

## Key paths and commands

- Rebuild a fuel snapshot (the job-scoped one used this session may be gone):
  `python3 adapters/claude-code/snapshot.py --out ~/.vibrant/snapshots` then use the
  dated dir. This session used a job-tmp snapshot at
  `/home/baron/.claude/jobs/60257a5e/tmp/realsnap/2026-08-14-workshop` (likely gone).
- Run: `python3 skills/vibrant-report/vibrant_report.py --harness claude-code
  --repos auto --repos-root ~/projects --snapshot <snap> --since 45.days.ago --out
  <out>`. `--repos auto` discovers the repos from the snapshot (before this fix the
  tool measured 9 percent of the rig; `coverage` block confesses gaps under 90 percent).
- Pattern classifier input: `python3 adapters/claude-code/fingerprint_evidence.py
  --snapshot <snap> --out <snap>/fingerprint-evidence.json`, then a subagent classifies
  review_regime / knowledge_practice / fine_topology into `fingerprint-labels.json`.
- Misery: extract the operator's reply corpus per session (blind, no model labels), a
  subagent scores it, write `misery-cache.json` in the snapshot dir.
- SEE renders: Playwright chromium at `~/.cache/ms-playwright`; you CANNOT judge pixels
  without rendering report.html and Read-ing the screenshot.
- Artifact (the shareable scorecard, update with `url=`):
  `https://claude.ai/code/artifact/1f5533a5-1b84-4ab9-aa69-f127e9a090fb`.

## SCORECARD UI (updated 2026-08-15, LATEST, read this first)

The report (`skills/vibrant-report/vibrant_report.py`) is now a single interactive
card. Branch `dyno-report-driver`, PUSHED, PR open: github.com/3dl-dev/vibrant/pull/1.
Private artifact (same URL across redeploys): claude.ai/code/artifact/
55d887a2-6b31-41ee-b645-d1e454092924 . Rebuild it from `report.html`'s `<body>` inner
into `$CLAUDE_JOB_DIR/tmp/vibrant-scorecard.html` then publish that path (same session)
or pass `url=` from a new one. The user is very happy with it ("WOW, this is great").

The card, top to bottom (all in `_hero_card` + `_card_maps`, JS by `render_walk`):
- HERO: combined SCORE = product of the ENABLED metrics (`#vb-score`). Magnitude is
  arbitrary; the tooltip says watch its movement.
- BREAKDOWN = the metric TOGGLES (`#vb-parts`, class `mtog`, data-m eff/flow/simp).
  Hover = preview (flip), click = hold (commit), min 1 enabled. Affordance: enabled =
  outlined, disabled = dimmed + strikethrough. Toggling drives BOTH the score (product
  of enabled) AND the descent objective (geometric mean of enabled normalized, the
  user's pick). No separate chip row (the breakdown IS the toggles).
- WAVEFORM (`render_waveform`, `#wave-svg`): one stacked-band sound wave, per period a
  mirrored bar split into eff(blue)/flow(teal)/simp(green) bands (`rect[data-m]`, dimmed
  when a metric is off). Each period a `.wv-bar` group; hover = scrub time.
- TWO fingerprint maps side by side IN the card (`som-maps-row`): "Where you work"
  (interactive, `id="map-you"`, `js_arrow`) + "The shared frontier" (compact). Portrait
  11x7 lattice, tapered oval (fewer cols top/bottom, whole hexes), 3dl ink-hex style.
- RECOMMENDATION `#vb-rec` below the maps: "-> shift toward <setup>" (no "optimizing
  for" prefix; the objective is implied). DESCRIPTION/PERFORMANCE `#vb-detail` is a
  SEPARATE line (hover a hex -> its setup+metrics; scrub -> the three-indicator perf).

Interactivity (all client-side JS, `_WALK_JS` raw string, emitted by `render_walk` which
now returns only CSS+script; embeds CELLS, PERIODS via `_timeline_periods`, CUR, AGG):
- Markers are HEX OUTLINES on the cells (not circles), all in one `.som-fx` group the JS
  owns (`marker()` helper server-side; JS reads each cell's polygon `points`).
- Scrub a period => three hex indicators: WERE (muted, that period's cell), BEST from
  there for the enabled objective (rust + arrow), WENT (teal, next period's cell);
  `#vb-detail` = "were X -> went Y (best Z). On <objective>, captured N% of the gain".
- Default (no scrub): "you" rust hex on the current cell + rust/objective arrow to best.
- Key JS fns: `enSet` (enabled+preview), `good`/`best` (geomean over cells, sessions>=2),
  `renderFx`, `scrubDetail`, `refresh`. `_rig_objective_metrics` builds per-rig
  eff/flow/simp; `som_map` attaches them per cell (flow direct per cell; eff/simp from
  the cell's dominant `model_roles` via the git attribution, an APPROXIMATION, flagged).

Metrics RE-SIGNED (all higher-is-better): misery->flow (100-misery), bloat->simplicity
(100-bloat, floored 0; the 100 anchor is PROVISIONAL, flagged). VIBRANT mark is now a
tiny hex-SOM (`_som_mark`, ink hexes + one rust peak). REMOVED: the standalone "your
steepest move" lever (`_lever_html` no longer in `render_html` body) AND its copy-paste
"apply it" prompt (flagged to the user; could return in a `<details>` under `#vb-rec`).
The separate big map + big shared map below the card were removed (maps live in the card).

VERIFY visually with headless chromium (python playwright NOT installed; use the binary
`~/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome`). Drive interactions by
injecting a `<script>` that dispatches events (`.wv-bar` mouseenter, `.mtog` click) then
`--screenshot`; catch JS errors with a `window.onerror -> document.title="JSERR:"` hack
(a ternary typo hid behind exactly this). PIL is available for cropping. Demo data lives
in `$JOBTMP=/home/baron/.claude/jobs/60257a5e/tmp`; snapshot at `$JOBTMP/realsnap/
2026-08-14-workshop` (som-cache.json = 11x7, shared-map.json = 2-op split demo). Pipeline:
driver `--dump-sessions` -> `session_features` -> `som_train --rows 11 --cols 7` ->
copy cache to snapshot -> reference codebook (`frontier/reference-codebook.json`, 11x7,
committed) -> `contribute_map` x2 halves -> `som_merge.merge` -> `shared-map.json`.

Open follow-ups (none blocking; user hadn't asked): restore the copy-paste agent prompt
under `#vb-rec` (offered); the shared-frontier map could get hover; per-cell eff/simp are
dominant-rig approximations (could be per-session if git complexity is joined to cells);
"were"/"went" often coincide (real data, operator stayed put). All 13 suites green,
deterministic, em-dash clean.

## SOM build status (updated 2026-08-15)

ALL FIVE items of the SOM plan are BUILT, tested, committed, and transfer-graded (hoist
`measure` profile: BUILT, transfer 4/4, the `learned-som-pipeline-holds` and
`federated-merge-holds` checks green on a clean target). Commits `59ee904` (item 1),
`b783eba` (item 2), `e6595db` (item 3 + `--dump-sessions` seam), `db623f0` (item 4 +
drift), `d850e5e` (item 5 federated merge), `efa2098`/`(hoist)` for the acceptance.

Item 5 was REDESIGNED with the operator: federation merges MODELS + per-cell aggregates,
never raw logs (memory `federation-by-model-merge`). Each operator publishes per-cell
`{cost, surv, support}` over a shared reference codebook; `core/som_merge.py` merges by
ratio-of-sums (Sigma cost / Sigma surv), giving a peer-validated field and a
surviving-work-weighted gradient. The weighting had a real bug caught on real data:
merging pre-divided ratios weighted by session count disagreed with the whole corpus in
20 of 32 cells; the ratio-of-sums fix reconstructs the whole EXACTLY (0/32). A privacy
floor rejects any contribution carrying a raw-log key. FedAvg of codebooks is a deferred
non-goal; v1 pins one shared reference frame.

- item 1 `adapters/claude-code/session_features.py`: per-session SHAPE vector (18-dim,
  one-hot arms + fixed-scale topology). Shape only, never outcome; fixed absolute
  scales so operators are comparable (federation-ready). `session-features@1`.
- item 2 `adapters/claude-code/som_train.py`: batch Kohonen SOM, deterministic
  power-iteration PCA init, STDLIB not numpy (byte-identical determinism; numpy over
  threaded BLAS drifts). `som-cache.json`, `som@1`. Real run: 9x9, mean QE 0.17.
- item 3 `som_map` + `load_som` in the driver: trajectory, time-windowed per-cell
  field (`d_per_survkb`), and the arm-change arrow GROUNDED in the operator's own
  sessions at the recommended arm (field shades, arm-change steers, topology excluded
  by construction). Also emits `drift` (the smoothed mood path). `som_consume.spec.md`.
- item 4 `render_som_map` in the driver: the map drawn. Cost-shaded lattice (LOG scale,
  the field has a long tail), a COMET TRAIL of drift dots (a connected line
  criss-crossed into noise; the operator oscillates between distant cells), current
  cell, the green sonnet-5 arrow. Self-contained SVG, theme-aware. VISUALLY VERIFIED by
  rendering the real report and reading the screenshot. `som_viz.spec.md`.

The SOM pipeline runs end to end on the real 232-session snapshot:
`vibrant_report.py --dump-sessions sessions.json` then `session_features.py` then
`som_train.py` then the driver reads `som-cache.json` from the snapshot dir.

## Honest open gaps

- item 5 (federated shared map) is NOT built; it is the teed-up decision (see below).
- The field is time-windowed in the SOM (item 3, 14-day default); the base git
  attribution is still all-time, by design.
- The misery cache is sparse (28 of 232 sessions scored this session); run the
  classifier over the full store.
- efficiency (changes/Mtok) still shows the opus-5 era slightly ahead; bloat and misery
  counter it, so the three-meter picture is honest, but there is no single clean
  "opus-5 failed" verdict, by design.
- The fingerprint-as-identity is only partly solved (N-dim bars); the trajectory model
  is the real fix and the SOM map is the next step.

## The SOM plan (decomposed, awaiting approval to dispatch)

Learned session-level SOM: sessions are the grain (232 local, thousands federated),
not the 12 rig-configs. Rigor: standard. Critical path 4 waves. Tiers: sonnet-5 x4,
opus-5 x1. Each item source-first, additive over the hand-written fallback.

1. Per-session feature vector (`session_features.py`): one-hot arms + normalized
   metrics, stdlib, deterministic. tier sonnet-5. no deps.
2. Out-of-band SOM trainer (`adapters/claude-code/som_train.py`, numpy ok): Kohonen
   lattice, PCA init, decaying neighborhood; writes `som-cache.json` (codebook +
   per-session BMU coordinate), seed-deterministic. tier sonnet-5. dep 1.
3. Driver consumption: read `som-cache.json`, build BMU trajectory over time + per-cell
   field (time-windowable) + downhill gradient; use learned coords when cached else the
   hand-written fallback; deterministic. tier sonnet-5. dep 2.
4. SOM-map visualization (render_html): lattice cells shaded by the field, operator
   trajectory + current cell + gradient arrow; self-contained SVG. tier sonnet-5. dep 3.
5. Federated shared map (`core/frontier.py`): trainer ingests an anonymized multi-
   operator corpus; every operator is a point on one shared map, the frontier optimum a
   cell on it. tier opus-5. deps 2,3,4.

Dispatch options presented to the user: (a) fork-swarm (subagents build 1 to 5 in dep
order, like the fork that built the hand-written model); (b) `rd init` a tracked board
then `/swarm-dispatch`. rd is NOT initialized in this repo. Awaiting the user's choice.

## User working style (hard-won, apply)

- Read tokens cost about 100x output; be terse, tables over paragraphs, turn-final
  messages short. Lead with the answer or the number.
- Decide by default; if you wrote a recommendation, that is the decision. But metric
  and philosophy changes are the user's call (they reshaped the metric repeatedly).
- The user will call BS hard ("useless", "spear through the heart", profanity). Take it
  as signal: find the real metric, do not defend the tool.
- Falsifiability is an instakill: never present unverified as fact; ground every claim
  in the user's own data, and check it before claiming it.
- Visualizations must be self-evident with few words; if it needs three paragraphs to
  explain, the visualization failed. Collapse detail behind `<details>`.
- Show the actual output for approval; do not declare "good" from a grader verdict.
- Attribution matters (PAD/ALMA got cited).
- The user thinks at the architecture level (PAD analogy, embeddings, gradient descent,
  SOM, control theory). Engage there, do not dumb it down.

## Federated map: wired end to end (updated 2026-08-15)

The three integration wires are BUILT, tested, graded (hoist BUILT, transfer 5/5, adds
`federated-map-wired`), commit `0b70c5e`:

1. `frontier/reference-codebook.json` (v1, hash `b1c76597`): the committed shared frame.
2. `adapters/claude-code/contribute_map.py`: the producer (`--dump-sessions` metrics +
   reference codebook -> `som-contribution@1`, assigns on the SHARED frame via
   `som_train.bmu`, windowed cost/surv/support, discloses no logs). spec + test.
3. `render_shared_map` in the driver: reuses `render_som_map` (now with overridable
   title/subtitle/legend; also fixed a title/cell-tooltip variable-shadowing bug) to
   draw the pooled field, your cell, and the support-weighted frontier arrow.

Proven end to end on real data with the REAL tools: split the 232-session corpus into
two operators, each runs `contribute_map` against the committed frame, `som_merge.merge`
-> 32 valued cells, 22 corroborated by both, frontier arrow backed by 7 peer sessions
across 2 operators. Shared map screenshot verified.

## Consumption wired (updated 2026-08-15); remaining polish

The live report now renders BOTH maps. `load_shared_map` (next to `load_som`) reads a
`shared-map.json` (schema `vibrant/som-merged@1`) beside the snapshot; `render_html`
draws `render_shared_map(shared, current_cell, som_merge.merged_gradient(...))` after
the personal map, using `rig_space.som.current_cell` as the operator's cell (valid while
v1 pins one reference codebook == the operator's SOM frame). Absent artifact -> the
section is empty and the report is byte-identical. Commit `ebca926`, graded BUILT 5/5.

Verified by rendering the real 232-session report with a demo merged map present: the
personal "Where you work" map and "The shared frontier" both render top to bottom
(screenshots read at a glance). The two look similar ONLY because the demo splits one
operator's corpus in two; real peers diverge.

Remaining polish (none reserved, none blocking):
- GENERAL operator cell: compute the operator's shared-frame cell by
  `som_train.bmu(reference_codebook, features(latest session))` rather than reusing the
  learned-map `current_cell`, so it stays correct if an operator's own SOM frame ever
  diverges from the reference frame. Needs `session_features`+`som_train.bmu` in the
  driver (the driver already puts `core` and the adapter dir on the path).
- PUBLISH FLOW: fold `contribute_map` into the `vibrant-contribute` skill (one agent
  action to produce a contribution), and a commons step that runs `som_merge.merge` over
  collected contributions and publishes `shared-map.json`, the way
  `frontier/reference-frontier.json` is curated. See memory `federation-by-model-merge`.

Do NOT skip the shipping loop: source-first, update `hoist/config.json`, re-emit and
grade. The toolchain recipe that worked: fetch
`https://github.com/3dl-dev/hoistable/releases/download/operators-v0.5.0/hoistable-operators-0.5.0.tgz`,
verify sha256 `93c02ced...4200ad5`, unpack, then
`python3 builder/emit.py <repo>/hoist/config.json --operators-pin pin.json --out ...`,
then `emit.extract_config` + `hoist.hoist(cfg_path, target_dir=...)` for the grade
(current: BUILT, transfer 4/4).
