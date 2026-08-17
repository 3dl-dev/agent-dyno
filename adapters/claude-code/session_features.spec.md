# session_features.spec.md

`session_features`, the per-session feature extractor for the learned SOM.

## What it is

The SOM (item 2, `som_train.py`) learns a low-dimensional organization of the
operator's sessions from a feature vector per session. This tool produces that
vector. It is the grain change that the rig-space handoff calls for: the unit is a
single session (232 local, thousands federated), not one of the 12 rig-configs.

It is the learned upgrade's front door. The hand-written `_embed` in the driver
(`vibrant_report.py`, the `_FAN`/`_FIRE`/`_RIGOR` priors) stays as the fallback;
this extractor is what a learner reads instead of those priors.

## The one load-bearing rule: shape, not outcome

The vector encodes a session's **shape**: the configuration arms the operator chose
and the working-style topology those choices produced. It MUST NOT encode the
economic outcome (surviving work, dollars, efficiency, bloat) or the operator's
friction (misery, nudges, interrupts). Those are the **field** painted over the
learned map by the driver (item 3), and the gradient descends that field. If
outcome leaks into the features, the SOM organizes sessions partly by their verdict,
and "move to a better-region cell" stops meaning "change your setup." Shape in,
field over the top, gradient down the field. Keep them separate.

Concretely: friction signals present on the session metric dict (`nudges`,
`interrupts`, `ends_q`, `waste`/`killed`, `dollars`, `born`, `out_tok` as a volume)
are NOT features. Working-style signals the operator's *choices* produce (how wide
they fan out, how long sessions run, how much they touch the loop, their cache
posture) ARE features.

## Input

A list of per-session metric dicts, exactly the shape the driver already builds in
`vibrant_report.py` (`metric()`, the dict returned around the `"sid"` key). The
fields this tool reads:

- `sid` (str), `day` (str or null): identity and time. Carried through, not featurized.
- `engine` (str): `solo` | `delegate` | `workflow`.
- `routing` (str): `none` | `homogeneous` | `cross-family`.
- `effort` (str or null): `low` | `medium` | `high` | `xhigh` | `max`, else unknown.
- `model` (str): orchestrator model base (e.g. `opus-4-8`, `sonnet-5`).
- `worker` (str or null): worker model base, or `solo`/absent when not delegating.
- `fanout` (int): subagents dispatched (`wf_agents + plain_agents`).
- `n_turns` (int): assistant turns in the session.
- `touches` (int): turns the operator typed into (engagement).
- `cache_r`, `in_tok`, `cache_w` (int): read-side token split, for cache posture.

Unknown or missing fields fall to a defined default (below); the tool never raises
on a sparse dict.

## Output: the feature vector

`features(m)` returns a list of floats, all in `[0, 1]`, of length
`len(FEATURE_NAMES)`. Every component is computed by a **fixed absolute transform**,
never a corpus-relative one (no min-max over the batch, no z-score). Fixed scales
make two operators' vectors directly comparable on one shared map, which the
federated map (item 5) requires, and make the vector a pure function of the single
session with no batch dependency.

`FEATURE_NAMES` (order is the vector order; the schema pins it):

Categorical, one-hot (a recognized value sets its slot to 1.0, all siblings 0.0; an
unrecognized/missing value sets the reserved slot, e.g. `effort_unknown`, or leaves
all engine/routing slots 0.0 if truly absent):

1. `engine_solo`
2. `engine_delegate`
3. `engine_workflow`
4. `routing_none`
5. `routing_homogeneous`
6. `routing_cross_family`
7. `effort_low`
8. `effort_medium`
9. `effort_high`
10. `effort_xhigh`
11. `effort_max`
12. `effort_unknown`

Continuous, each already in `[0, 1]` by a fixed transform:

13. `orch_fire`: orchestrator model tier from the fixed `TIER` map (below). Missing
    model -> 0.5.
14. `worker_fire`: worker model tier from `TIER`, or 0.0 when solo / no worker /
    worker == `solo`.
15. `fanout`: `min(log1p(fanout) / log1p(FANOUT_CAP), 1.0)`, `FANOUT_CAP = 32`.
16. `turns`: `min(log1p(n_turns) / log1p(TURNS_CAP), 1.0)`, `TURNS_CAP = 200`.
17. `touch_rate`: `min(touches / max(n_turns, 1), 1.0)`.
18. `cache_read_pct`: `cache_r / (cache_r + in_tok + cache_w)`, or 0.0 when the
    denominator is 0.
19. `out_per_turn`: this is a **volume/verbosity of the engine's own output**, a
    style signal, not an economic outcome; it is derived from `orch_out` only if
    present, else omitted. To keep the vector purely shape and avoid any token-volume
    that reads as productivity, `out_per_turn` is NOT included. (Slot intentionally
    left out; see note.) 

Note on component 19: the first build ships 18 features (1 to 18). `out_per_turn`
was considered and rejected to keep the vector clean of anything that could be read
as "more output = better." If a future spec revision adds it, it lands as a new
schema version, not a silent append.

### The TIER map (fixed, absolute, federation-shared)

Mirror the driver's firepower ordering so the learned space and the fallback agree
on tier direction. In `[0, 1]`:

```
TIER = {
  "haiku-4-5": 0.15, "haiku-4-5-20251001": 0.15, "fable-5": 0.25,
  "sonnet-4-6": 0.55, "sonnet-5": 0.6, "opus-4-6": 0.85, "opus-4-8": 0.9,
  "opus-5": 1.0,
}
```

An unrecognized worker/orchestrator base maps to 0.5 (orchestrator) or, for a
worker, 0.0 only when there is genuinely no worker; an unrecognized *named* worker
maps to 0.5. Base the model string with the same `.split("[")[0]` /
`replace("claude-", "")` normalization the adapters already use.

## API

- `SCHEMA = "vibrant/session-features@1"`.
- `FEATURE_NAMES`: the ordered list above (length 18).
- `TIER`, `FANOUT_CAP`, `TURNS_CAP`: module constants.
- `features(m: dict) -> list[float]`: pure, deterministic, length `len(FEATURE_NAMES)`,
  every element in `[0, 1]`. No batch, no corpus, no randomness.
- `feature_matrix(sessions: list[dict]) -> dict`: returns
  `{"schema": SCHEMA, "names": FEATURE_NAMES, "rows": [{"sid","day","vec"}, ...]}`,
  rows in input order (the caller sorts). `vec` is the `features()` output.

## CLI

```
python3 session_features.py --sessions sessions.json [--out matrix.json]
python3 session_features.py --selftest
```

`--sessions` is a JSON array of per-session metric dicts (what the driver builds; a
`--dump-sessions` path on the driver or an equivalent extractor supplies it). Output
is the `feature_matrix` object, `json.dumps(..., indent=2, sort_keys=True)`, written
to `--out` or stdout. `--selftest` runs the acceptance fixture, exits 0/1.

## Determinism and constraints

- Stdlib only. Pure arithmetic; `math.log1p`. No numpy in this tool (the trainer that
  consumes it may use numpy; this front door stays stdlib so the driver could import
  it too if a future item wants live projection).
- `features()` is a pure function of one dict. `feature_matrix` is a pure function of
  the list. Re-running on the same input is byte-identical.
- No em-dashes anywhere.

## Known limits

- Fixed caps (`FANOUT_CAP=32`, `TURNS_CAP=200`) saturate the extremes; a session with
  400 turns and one with 200 both read 1.0 on `turns`. That is deliberate: the tail is
  rare and the SOM cares about organization, not the exact magnitude of an outlier.
- The vector is shape only by design; a reader wanting to know if a shape *paid off*
  must join to the field (the driver's per-cell economics), which is exactly the
  separation the SOM depends on.

## Schema v2 (proposed): the rig as an orchestration mix

Status: BUILT. `SCHEMA = "vibrant/session-features@2"`, length 18. Decisions taken:
the capability tier is retired from the fingerprint (option (a) below), so
`orch_fire` and `worker_fire` are removed and `depth` + `family_diversity` are
appended; the vector stays length 18. `local_share` is DEFERRED (no endpoint-origin
signal in the adapter yet), tracked with cross-job lineage. Everything else in v1
(engine, routing, effort, fanout, turns, touch_rate, cache_read_pct) is unchanged.

### Why

v1 describes a session's topology with a 3-way `engine` one-hot and collapses the
whole worker population to ONE scalar (`worker_fire`, the dominant worker tier). That
cannot express what a rig actually is. A rig is the shape of the whole orchestration:
how DEEP it nests (one agent, a layer of workers, sub-orchestrators under those), how
WIDE it fans, and the MIX of model classes across the entire tree, whether reached
directly or nested, "all opus all day" versus a spread of opus / sonnet / haiku that
even pulls in small and local models for the cheap work. Two rigs that both read
`worker_fire = 0.6` today can be an all-sonnet flat delegate and a deep opus-over-
haiku-over-local orchestration. v2 gives the map the axes to tell them apart. There
are infinite permutations with regional similarities, which is precisely what the SOM
organises: v2 just hands it coordinates that carry the distinction.

Per the four-slot schema, all three new dimensions land in ONE slot, the fingerprint
axis. No fifth slot; `fanout` (breadth) already exists, so the net-new axes are depth
and the two mix axes.

### Attribution scope

Features are computed over the **in-session orchestration tree**: the main session
plus its nested subagents as recorded under the session directory (the recursive
`subagents/**` files the extractor already reads). CROSS-JOB trees, where the operator
drives workers as separate top-level jobs rather than in-session subagents, are OUT OF
SCOPE for v2: there is no parent/driver link in the session records to assemble them.
That gap is tracked as a separate adapter task (add a lineage signal), and until it
lands, a driven fleet of separate jobs still reads as many independent leaf sessions.

### New input fields (on the per-session metric dict)

- `depth` (int): the maximum orchestration nesting depth of the in-session tree. `0`
  when the session dispatched no agents (solo); `1` for a flat layer of workers; `2`
  when a worker itself orchestrated (a sub-orchestrator); and so on. Derived from the
  nesting depth of the `subagents/**` file tree. Missing -> fall back to the engine
  class: solo -> 0, delegate/workflow -> 1.
- `tree_mix` (dict `model_base -> weight`, or `model_base -> {weight, local}`): the
  output-token-weighted census of every model that ran ANYWHERE in the tree, the
  orchestrator itself included (the orchestrator's model is part of the rig, not outside
  it). Generalises v1 `submix` (workers only, one level) to the whole tree. The optional
  `local` boolean per entry is an objective endpoint fact (self-hosted vs vendor-hosted)
  that feeds `local_share`; absent -> `local_share` is deferred, not guessed. Missing
  `tree_mix` -> synthesize from `model` (the orchestrator, full weight) plus `submix` if
  present, so v1 dicts still embed.

### No capability priors (why there is no tier here)

A rig's fingerprint encodes only OBSERVABLE STRUCTURE: how deep the orchestration
nests, how wide it fans, how many distinct model families it draws on, and (when the
adapter can tell) how much runs on local endpoints. It never asserts that a model or a
mix is good. Whether a shape pays off is MEASURED by the field, the survival economics
per cell, never predicted by a prior. A single capability tier (v1's `TIER` scalar) is
a bias and a category error: capability is multi-dimensional and task-specific, a local
model can be weak at general reasoning yet strong at code, so no scalar ranking holds
across tasks. v2 therefore classifies models only by observable, vendor-given facts and
leaves "how good" to the data.

Model FAMILY is the objective grouping used below: the product-line stem of the model
name (`opus`, `sonnet`, `haiku`, `qwen`, `llama`, ...), taken from the same base
normalization the adapters already apply, with NO ordering among families. Grouping by
a vendor's own family name is observation; ranking families by a firepower number was
the bias.

### New features (fixed absolute transforms, each in [0, 1])

Continuous, appended after the retained v1 features (positions 17 and 18 once
`orch_fire`/`worker_fire` are removed). Numbered here by role, not slot index:

19. `depth`: `min(depth / DEPTH_CAP, 1.0)`, `DEPTH_CAP = 4`. Solo = 0.0, one layer =
    0.25, a sub-orchestrator = 0.5, three deep = 0.75, four or more = 1.0. Linear (not
    log): each level up to the cap is a distinct, meaningful rig change, unlike raw
    fanout counts where 20 vs 21 agents is noise.
20. `family_diversity`: the normalized Shannon entropy of the tree's model-FAMILY
    distribution, output-token weighted. Sum weights per family, normalize to a
    distribution `p`, then `H(p) / ln(FAMILY_CAP)` with `H(p) = -sum_f p_f * ln(p_f)`
    over families present and `FAMILY_CAP = 6` (a fixed cap keeps it absolute and
    federation-comparable, not relative to how many families this one tree happened to
    use). One family, however many versions of it (all opus) -> 0.0; an even spread
    across six or more families -> ~1.0. This is the "all opus all day" versus "a real
    mix" axis, with no claim about which is better.
21. `local_share`: the output-token-weighted fraction of the tree that ran on LOCAL /
    self-hosted endpoints, an objective deployment fact the adapter reports (the
    endpoint origin), NOT inferred from the model name or any tier. Requires a per-model
    `local` boolean in the `tree_mix` metadata. If the adapter cannot yet distinguish
    local from vendor-hosted, this feature is DEFERRED (like cross-job lineage) rather
    than guessed, and v2 ships with features 19 to 20 until the marker exists.

`family_diversity` is an absolute function of the fixed `FAMILY_CAP`, not corpus-
relative, so it stays federation-comparable like every other component. There is no
capability tier in these axes.

### Deprecating the tier scalar

v1's `orch_fire` and `worker_fire` (features 13, 14) were the same bias: a hardcoded
capability ranking of models. DECIDED (option (a)): they are RETIRED from the
fingerprint, and capability is measured by the field. The `TIER` constant is removed
from this module. Shape stays purely structural. This reshapes the learned space (it is
not an append), which is why it rides the @2 version bump and forces a retrain; a @1
codebook no longer matches `FEATURE_NAMES` and is correctly rejected by the contribute
guard. (Options considered and not taken: (b) keep them for continuity; (c) replace with
a non-capability "how much machinery" scalar such as model count.)

Not yet migrated: the driver's hand-written fallback `_embed` / `_FIRE` in
`vibrant_report.py` still carries the same tier prior. It is the no-SOM fallback, a
separate surface, and is tracked to move off tier so the fallback and the learned space
agree with this principle.

### Federation and versioning

The feature schema is the shared coordinate system of the federated map (item 5). v2
is a version bump every federated map adopts together; a v1 map and a v2 map do not
share coordinates and must not be merged. This is a governance-visible change, gated on
sign-off, not a silent append. The only shared constants v2 adds are the objective
family grouping (from model names) and `FAMILY_CAP`; NO capability tier is introduced.

### Acceptance (to accompany the build, not this draft)

- Length 18 (`local_share` deferred), every element in [0, 1], pure and deterministic
  (byte-identical re-run). No `orch_fire`/`worker_fire`; no `TIER` constant.
- Solo opus session: `depth = 0`, `family_diversity = 0` (one family).
- All-opus workflow with 20 agents: `family_diversity = 0` despite high `fanout`; the
  mix axis is orthogonal to breadth.
- Flat opus->qwen(local) delegate: `depth = 0.25`, `family_diversity > 0`, and
  `local_share` = the qwen token share when the `local` marker is present.
- Deep opus->sonnet->haiku (sub-orchestrator): `depth = 0.5`, `family_diversity`
  reflects three families.
- v1 dict with no `depth` / `tree_mix`: embeds via the documented fallbacks, no raise.

## Schema v3 (proposed): coordination

Status: PROPOSED, not yet built. `SCHEMA = "vibrant/session-features@3"`. Draft for review;
no code until the axis is confirmed. A v3 vector is a superset of v2: the retained v2
features are unchanged, one new fingerprint axis appends. See docs/claims.md X8 and the
coordination-signal probe (2026-08-17) that established feasibility.

### Why

v2 describes the SHAPE of an orchestration by its depth, breadth (fanout) and model-family
mix. It cannot tell whether the workers actually WORK TOGETHER. Two workflows with identical
depth, fanout and family mix can be entirely different: one where sub-agents build on a shared
body of code, and one where they SILO (each fans out onto its own files and never interacts).
Anthropic's multi-agent research finds this coordination-vs-siloing behaviour, not the
flat-vs-hierarchical scaffolding, is what decides whether more agents help. Our own probe
confirms it is real and measurable: across 113 in-session multi-agent trees, orchestrations
are overwhelmingly siloed (mean pairwise file-overlap ~0.00). v3 gives the map an axis for it.

Per the four-slot schema this lands in ONE slot, the fingerprint axis. No fifth slot.

### No capability / quality priors (why this is NEUTRAL)

`coordination` measures only observable STRUCTURE: how much sibling workers touch the same
files. It is NOT a quality claim. High overlap can mean genuine coordination (workers building
on shared code) OR conflict (workers stepping on each other); low overlap can mean clean
parallelism OR missed collective intelligence. The fingerprint never adjudicates which: as
with every axis, whether a shape paid off is MEASURED by the field (survival per token, cargo),
never asserted. Do not encode "coordinated is better" anywhere.

### Attribution scope

Computed over the IN-SESSION orchestration tree only: the sibling sub-agents recorded under the
session directory, and the files each one edited. CROSS-JOB siloing (workers driven as separate
top-level jobs) is out of scope for the same reason as v2 and the cargo work: no lineage link.
Tracked with that gap.

### New input field (on the per-session metric dict)

- `worker_files` (list of lists of str, or null): one entry per in-session worker (sub-agent),
  each the set of file paths that worker edited (Edit / Write / MultiEdit / NotebookEdit
  `file_path`). The extractor already reads the `subagents/**` transcripts; this collects the
  edited paths per sub-agent. Missing / fewer than 2 workers -> `coordination` is 0.0 (a lone
  or single actor cannot coordinate), never raises.

### New feature (fixed absolute transform, in [0, 1])

Continuous, appended after the retained v2 features:

- `coordination`: the share of the tree's edited files that more than one worker touched,
  `min(1.0, shared / distinct / COORD_CAP)` with `COORD_CAP = 0.20`. `shared` = count of
  files edited by >= 2 workers; `distinct` = count of files edited by any worker. 0.0 when
  there are fewer than 2 workers or no edits. Fully siloed (disjoint files) -> 0.0; a fifth
  or more of the touched files shared across workers -> ~1.0. The cap (like FANOUT_CAP /
  DEPTH_CAP) is fixed and federation-shared, chosen because real values cluster low (siloing
  is the norm), so the axis needs the low range expanded to have resolution.

### Federation and versioning

v3 is a version bump every federated map adopts together; a v2 map and a v3 map do not share
coordinates and must not be merged. Gated on sign-off. The only shared constant v3 adds is
`COORD_CAP`; no capability tier is introduced.

### Acceptance (to accompany the build, not this draft)

- Length v2 + 1, every element in [0, 1], pure and deterministic (byte-identical re-run).
- Solo session (no `worker_files`): `coordination = 0.0`.
- Two workers, fully disjoint file sets: `coordination = 0.0`.
- Two workers sharing all files: `coordination = 1.0` (shared/distinct = 1 >= COORD_CAP).
- Twenty workers, ~10% of files shared: `coordination = min(1, 0.10/0.20) = 0.5`.
- v2 dict with no `worker_files`: embeds via the fallback (0.0), no raise.
