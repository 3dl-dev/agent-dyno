# spec: frontier (the federation engine)

The deterministic operations that make a frontier a *federated* commons instead of
a single file people hand-edit. A frontier is a `reference-frontier.json`
(`vibrant/frontier@2`): `{schema, note, axes, entries[]}`. This tool never talks
to a network and never decides policy; it transforms frontier files so a team or an
enterprise can run their own board, keep it internal, and share upward only a
summary they choose. Stdlib only, harness-neutral, deterministic.

## Why it exists

Federation was a convention (hand-edit or PR a parent file). Two moves need code so
they are honest and repeatable:

1. **Roll up, without mandatory push.** A team keeps its own frontier. Members'
   entries collect into it locally; nothing leaves the team's control. `merge` is
   that local roll-up: fold child frontiers into a parent, deduplicated, re-sanity
   checked. It is an operation the frontier's owner runs, never an automatic push.
2. **Share a summary, not the raw entries.** An enterprise will not publish every
   member's run, but may allow an anonymized *aggregate* out. `summarize` turns a
   frontier into one entry per shape (engine x effort x role-tier x review regime),
   carrying the aggregate vector and the counts, and nothing that identifies a run
   or a person. That summary is what an org pushes to a parent frontier, by choice.

## Interface

```
frontier.py init <path> [--note "..."] [--force]
frontier.py validate <frontier.json>
frontier.py merge --into <parent.json> <child.json> [<child.json> ...] [--out <path>]
frontier.py summarize <frontier.json> [--date YYYY-MM-DD] [--min-samples N] [--out <path>]
```

Importable (the deterministic core other tools consume):

- `new_frontier(note="") -> frontier` : an empty, valid frontier skeleton.
- `validate(frontier) -> list[str]` : tier-0 sanity issues, empty if clean.
- `merge(parent, children) -> frontier` : parent with children's entries folded in.
- `summarize(entries, date, min_samples=1) -> list[entry]` : anonymized aggregate
  entries, one per shape.

### init (stand up a board, so setup is not a scavenger hunt)

`init` writes a fresh, valid empty frontier (`{schema, note, axes:{}, entries:[]}`)
to `<path>`, refusing to overwrite an existing file unless `--force`, and prints the
two next steps a user would otherwise have to discover: point the viewer
(`leaderboard/vibrant.html`) at the file, and set `$VIBRANT_FRONTIER=<path-or-url>` so
`vibrant-report` compares against it and `vibrant-contribute` writes to it by default. This
is the whole "run your own leaderboard" setup: a file plus a config line, no server.

## Method (every step deterministic)

### validate (tier-0 sanity, the floor every entry must pass)

For each entry: `waste_pct` in [0,100]; `cache_read_pct` in [0,100]; every present
vector number finite and non-negative; `samples` a positive integer; required keys
(`engine`, `vector`, `date`) present. Return a stable, sorted list of human-readable
issues naming the offending entry id and field. This is the same floor
`vibrant-contribute` applies before writing, reused so a merged or summarized frontier
is checkable in one call.

### merge (local roll-up, never a push)

Fold each child's `entries` into the parent's, in order, **deduplicated by `id`**:
a child entry whose `id` already exists in the parent (or in an earlier child) is
skipped, not overwritten, so re-running merge is idempotent and a parent's own
curated entry always wins. The parent's `schema`, `note`, and `axes` are preserved;
only `entries` grows. Output ordering is the parent's entries first, then each
child's new entries in child-then-file order, so the bytes are a pure function of
the inputs. A merged frontier that fails `validate` is still written but the issues
are reported (merge transforms, it does not silently drop).

### summarize (the anonymized roll-up an org chooses to share)

Group entries by **shape**: the tuple `(harness, engine, effort,
orchestrator-tier, worker-tier, review_regime, horizon)`, reading
`model_roles.orchestrator` / `model_roles.worker` for the tiers. Within a shape,
emit ONE summary entry:

- `id`: `summary-<engine>-<effort>-<8-hex of a stable hash of the shape>`
  (deterministic, no clock, no randomness).
- the shape fields verbatim (engine, effort, model_roles, review_regime, horizon,
  harness).
- `vector`: for each axis that appears across the shape's entries, the **median**
  of the present values (samples-unweighted, so one loud run cannot dominate; the
  count carries the weight separately). Median of an even count is the mean of the
  two middle values. Deterministic given sorted inputs.
- `samples`: the sum of the shape's entries' `samples` (total sessions behind it).
- `entries_summarized`: how many entries rolled into this summary.
- `aggregate: true`, and `proof: "tier-1-aggregate"` (an aggregate is a self-report
  of a group; it never inherits a member's higher tier, and never claims Tier 3).
- `technique` / `lever`: dropped to a generic, shape-derived line, because
  per-entry prose can leak specifics; a summary carries numbers, not stories.
- `date`: the supplied date (deterministic; the caller passes it, the tool has no
  clock).

Shapes with total `samples` below `--min-samples` (default 1) are omitted, so an
org can require a k-anonymity floor before a small cell is shared. The output is a
frontier object (`schema`, empty `note`/`axes` carried from input, `entries` =
the summaries), sorted by `id`, so it is a drop-in a parent can `merge`.

**Anonymity guarantee, stated:** a summary entry carries only shape + aggregate
numbers + counts. No entry id from the source, no technique prose, no repo, no
identity. Summarize is the operation that lets an enterprise share upward without
handing over individual runs.

## Determinism and portability

Output is a pure function of the input files and the supplied `--date`. No clock, no
randomness, no network, no set-iteration nondeterminism (all grouping sorts its
keys). Same inputs, same bytes.

## Acceptance

`test_frontier.py` builds a fixture frontier with known entries across two shapes
and asserts: (0) `new_frontier` is a valid, empty board; (1) `validate` flags an
out-of-range `waste_pct` and passes a clean file; (2) `merge` folds children in, skips duplicate ids, and is idempotent
(merging twice equals merging once); (3) `summarize` emits one entry per shape with
the median vector and summed samples, marks it `aggregate` / `tier-1-aggregate`,
carries no source id or technique prose, and honors `--min-samples`; (4) a second
run on the same inputs and date is byte-identical.
