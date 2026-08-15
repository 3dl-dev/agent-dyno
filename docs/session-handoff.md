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

## SOM build status (updated 2026-08-15)

Items 1 to 4 of the SOM plan are BUILT, tested, committed, and transfer-graded (hoist
`measure` profile: BUILT, transfer 3/3, the new `learned-som-pipeline-holds` check
green on a clean target). Commits `59ee904` (item 1), `b783eba` (item 2), `e6595db`
(item 3 + `--dump-sessions` seam), `db623f0` (item 4 + drift), `efa2098` (hoist).

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

## Immediate next action: item 5 (federated shared map), teed up

Items 1 to 4 are a complete, shippable, graded local learned-SOM. Item 5 is the
federation surface and is the operator's call because it touches two reserved things:

1. LAYERING: `som_train.py` is harness-neutral (pure vector math) but currently lives
   in `adapters/claude-code/`. The shared-map builder wants it in `core/`. Recommended:
   relocate `som_train.py` (+ spec + test) to `core/` as part of item 5, since it is
   shared infrastructure, and have the adapter keep a thin re-export if needed.
2. CONFIDENTIALITY POSTURE: the shared corpus must be anonymized. The existing floor is
   `core/frontier.py` `summarize()` (no identities, median vectors, no source id, no
   prose). Recommended contract, following that floor: each contribution is
   `{op: <opaque-hash>, sessions: [{vec, day, dollars, survkb}]}`, no sid, no repo, no
   free text. Home: a new `core/shared_map.py` (keep frontier.py's three ops clean),
   spec + test first.

Design sketch (build after the operator greenlights the two decisions above): train
ONE SOM on the union of all operators' vecs with a PINNED lattice (som@1 with fixed
`--rows`/`--cols`); global field per cell pooled across operators (windowed); the
frontier-optimum cell = min field with min support; each operator is a point (their
recent BMU centroid) with a gradient toward the optimum. Reuse `render_som_map` for
the shared map with operator points overlaid. Output `shared-map@1`.

Do NOT skip the shipping loop on item 5: source-first, update `hoist/config.json`,
re-emit with the toolchain (pin `0.5.0`, fetch+verify sha256), grade on a clean target.

The toolchain self-extract + grade recipe that worked this session: fetch
`https://github.com/3dl-dev/hoistable/releases/download/operators-v0.5.0/hoistable-operators-0.5.0.tgz`,
verify sha256 `93c02ced...4200ad5`, unpack, then
`python3 builder/emit.py <repo>/hoist/config.json --operators-pin pin.json --out ...`,
then `emit.extract_config` + `hoist.hoist(cfg_path, target_dir=...)` for the grade.
