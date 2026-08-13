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
   cells with N below a floor, non-overlapping fuel/git windows.

## The functional surface: one number, one lever, a measurable delta

The user sees three things and nothing else:

1. **The topline EQ.** `surviving functionality per Mtok` -- surviving complexity
   (git decision points, a functionality proxy) over total tokens processed.
   **Larger is better** (matching the high-score instinct), unbounded, and a
   ratio so volume cannot game it -- burning tokens for no lasting functionality
   lowers it (the inversion of naive tokenmaxxing). DORA change failure rate rides
   alongside as the delivery-quality lens. This is the meter; surviving-KB and
   dollars are depth lenses. Honest seam: functionality is git-side and tokens
   session-side, so the window number is a straight ratio; scoping tokens to the
   repos' own sessions (and slicing by model/effort) needs the git<->session join.
2. **One lever.** The single fingerprint tweak with the largest predicted gain:
   the operator's worst same-shape cell versus the same-shape frontier entry that
   beats it. Reported as a plain tweak (the frontier entry's technique) plus a
   **predicted new topline** (recompute the blended EQ as if that cell ran at the
   frontier entry's efficiency). If no same-shape entry beats the operator, there
   is no lever; say so, never invent one.
3. **Measure.** With `--baseline <prev report.json>`, show the actual EQ move
   since last run beside what was predicted. This closes the predict-then-measure
   loop: tweak the rig, re-run, see if the number moved as promised.
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
  native SVG tooltips. No external assets, no scripts. Slicing the fuel-and-work
  series by model / effort / engine, and hourly granularity (needs per-turn
  timestamps), are the next increment.

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

## v1 scope and deferrals (stated, not silent)

v1 implements steps 1, 2, 4, 5, 6, 7 and the full output/governance/determinism
contract. **Step 3 (git-side per-engine attribution via `horizon_attribute`, the
durable "which engine's committed lines survived" cut) is deferred to v2** and is
not yet folded into `report.json`. Until then the narrator may run
`core/horizon_attribute.py` per repo by hand for that cut; it is not part of the
turn-key guarantee. This deferral is deliberate: v1 covers the same-session vector,
the numerator, and the same-shape comparison end-to-end and tested; the git-side
engine join needs commit-to-session matching that earns its own fixture.

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
4. a second run on the same fixture and date is byte-identical.

A build that does not pass this is not a valid build. The skill may not ship a
number this driver did not produce.
```
