# spec: misery (the second meter)

Misery is efficiency's twin. Efficiency answers "is my rig cheap?" (surviving work
per token). Misery answers "is my rig bearable?" (how much the operator fought it).
Both are functions of the **same input**: the rig fingerprint. Misery is not a
property of a model. Held to one model (opus-4-8), moving only the orchestration
topology swings measured misery ~15 points (solo ~28, workflow ~44) against a model
effect of ~5, so the dominant term is the fingerprint, not the model. The tool
therefore measures misery the way it measures efficiency: one number over the whole
parameter space, sliced by every arm, so the operator can find the region of their
fingerprint that is both cheap and bearable.

## What it is and is not

- **A second meter, not a sub-score.** Misery is reported beside the topline and
  never folded into EQ, exactly as the babysitting index is not. Pricing your
  frustration against tokens is an operator-owned choice; the tool gives you both
  numbers and the tradeoff, not a blend.
- **Operator-relative by construction.** Misery is measured from *your* reactions to
  *your* runs. A faster reader who never registers verbosity produces a low score,
  correctly. It is comparable only within one operator, across that operator's own
  fingerprint cells. It is never comparable across people, and never a verdict about
  a model. This is not a caveat bolted on; it is why the number is trustworthy and
  why it survives contact with "works for me": the answer is "then your number is
  low, run it on your logs."
- **Earned from evidence, scored blind.** The classifier reads the operator's own
  turns (and the model's handovers) with the model identity **hidden**, so it cannot
  parrot a model's public reputation. A high score must be backed by a verbatim quote
  from the operator's replies.

## Method (inference out of band, consumption deterministic)

Same shape as the fingerprint-labels layer: an LLM classifies once, out of band, and
writes a cache; the driver consumes the cache as a pure function.

1. **Evidence (adapter, `adapters/<harness>/misery_evidence.py`).** Per session,
   package a compact, blind bundle: the operator's reply texts in order, plus minimal
   handover context (whether the model ended a turn handing work back), with **no
   model identity, no timestamps that leak ordering across sessions, and no raw
   assistant prose beyond what a reply quotes**. Sessions are presented under opaque
   ids.
2. **Classify (skill, Haiku triage -> Sonnet score; cost-gated).** For each session,
   emit `{score: 0-100, tags: [...], evidence: "<verbatim operator quote>"}`. `score`
   is 0 (smooth, calm iteration, approvals) to 100 (constant fighting). `tags` are
   drawn from a fixed vocabulary: `frustration`, `course-correction`, `scope-complaint`,
   `verbosity`, `repetition`, `instruction-drift`, `clean`. Score sentiment and
   friction only, never productivity: a session may ship a mountain and be miserable,
   or ship nothing and be pleasant.
3. **Cache.** Write `misery-cache.json` (default: alongside the snapshot), schema
   `vibrant/misery@1`, keyed by session id:
   ```
   { "schema": "vibrant/misery@1",
     "sessions": { "<sid>": { "score": 0-100, "tags": [...],
                              "evidence": "<verbatim quote>" }, ... } }
   ```
   Scores + tags + one quote only, no raw transcript. The operator may hand-correct
   any score (their experience is the ground truth).
4. **Consume (driver).** Read the cache; attach `misery` to each session exactly as
   same-session survival is attached. A session absent from the cache has misery
   `null` and is excluded from misery aggregates (a no-cache run is unchanged, and the
   efficiency meter is untouched). Then aggregate misery as a meter over the
   fingerprint:
   - **Overall:** the mean misery across scored sessions, on the card beside the
     efficiency number.
   - **By every arm:** a misery value for each cell of every slice the driver already
     cuts (`by_model` / `by_worker` / `by_model_roles` / `by_effort` / `by_engine` /
     `by_routing`), so misery is sliceable and holdable-fixed exactly like efficiency.
     The mechanism that proves "the wrong fingerprint, not the model" is a first-class
     query: slice misery by topology holding model fixed.
   - **By rig:** a misery column beside surviving-work in the `orchestrator -> worker`
     attribution, so each rig config shows cost and misery together.
   - **Over time:** misery per era on the timeline, efficiency's twin, so an operator
     abandoning a rig shows as a misery drop the efficiency line could not explain.

## The lever goes 2D

With two meters over one fingerprint, the frontier is a plane, not a line. The lever
stops saying "adopt the most efficient rig" and says "here is your efficient-and-
bearable region": the cell that is cheap enough and low-misery, naming the arm to
move (often topology, not model). A rig that wins on efficiency but tops misery is
surfaced as a tradeoff, never silently recommended.

## Governance

Misery is self-measurement of your own workflow, engine-craft only. The driver never
emits a cross-operator or person-versus-person misery comparison, and never publishes
misery as a model verdict. Federation shares efficiency **shape** only; your misery
stays local (an org roll-up, if any, carries no per-operator misery). Stamped
governance-clean like the rest of the bundle.

## Cost gate

Identical to the turn-quality / fingerprint-labels gate: the classify pass spends
inference, so it is opt-in above a threshold expressed as a ratio to the window's own
baseline usage (tokens per model, never dollars; default ask above ~1% of weekly
output). The operator sees the ratio before the spend and the tokens actually spent
after. The tool eats its own dog food: the assessment's cost is justified by the rig
change it unlocks.

## Determinism and portability

Output is a pure function of (misery-cache, the same inputs the efficiency pipeline
uses). The inference is out of band (the skill writes the cache once, operator-
correctable); the driver's consumption is deterministic: same cache, same day, same
bytes, on any model that runs the driver. The evidence bundle is the adapter
contract's job, so a second harness with equivalent transcripts yields a comparable
misery meter.

## Acceptance (`test_misery.py`)

Given a fixture `misery-cache.json` over fixture sessions with known scores and
fingerprints, the driver must:

1. attach per-session misery and compute the **overall** mean beside the topline,
   without touching EQ (the efficiency number is byte-identical with and without the
   misery cache);
2. produce a misery value for **every** fingerprint slice it cuts, and, holding
   `model` fixed, show misery varying across `engine` (topology) cells (the "wrong
   fingerprint, not the model" invariant);
3. carry a **per-rig** misery beside surviving-work in the `orchestrator -> worker`
   attribution, and a **per-era** misery on the timeline;
4. emit `null`/absent misery cleanly when the cache is missing (efficiency output
   unchanged), and never fold misery into EQ;
5. stay governance-clean (no cross-operator misery) and deterministic (byte-identical
   re-runs from the same cache).
