---
name: dyno-report
description: Measure the fuel-efficiency of your AI coding setup from your own logs and git history, surviving work per token, split by engine / model / effort / review regime, compared against same-shape setups on the frontier. Runs on your machine, nothing uploaded. Self-improvement, never a ranking of people against product. Use for "how efficient is my setup" or "which engine is cheapest per surviving line".
argument-hint: [--repos <path,path>] [--since 30.days.ago]
---

# Dyno report

The numbers come from a deterministic driver, not from you. Your job is three
things a model cannot get wrong: read the constitution, run the driver, narrate
what it returns. Do not compute vectors, survival, or dollars yourself; if a
number is not in `report.json`, do not report it.

## 1. Read the constitution first (gating)

Read `docs/governance.md`. You measure the operator's **own engine** for
self-improvement. Never rank an individual against product outcomes, never
compare people. If asked for that, decline and cite the document; roll up to
team/BU for tokens-per-product instead. The driver stamps `report.json` with a
governance-clean assertion; do not emit anything that contradicts it.

## 2. Build the fuel snapshot (once per run, if absent)

The driver needs a snapshot of the harness's derived per-session metrics. For
Claude Code:

```
python3 adapters/claude-code/snapshot.py --out <snap-parent>
```

Reuse an existing snapshot dir if you have a recent one. For pi / opencode, if
the adapter is a stub, there is no fuel side yet; run the numerator only and say
so.

## 3. Run the driver

```
python3 skills/dyno-report/dyno_report.py \
    --harness claude-code --snapshot <snap-dir> \
    --repos <repo1,repo2,...> --since 30.days.ago --out <out-dir>
```

`--repos` is the repos the operator actually codes in (git survival is read from
each). It writes `report.json` (the contract) and `report.md` (a rendered
report). Everything downstream reads `report.json`.

## 3b. Classify the pattern dimensions (optional, cached, cost-gated)

Three of the six fingerprint dimensions (docs/taxonomy.md) are patterns a counter
cannot place: **fine topology**, **review regime**, **knowledge practice**. You
classify them once and cache the result; the driver then consumes the cache
deterministically. This is what the model is allowed to do (the driver stays a
pure function). Skip it if the operator only wants the topline; the report is
complete without it, the three slots just read "pending-classification".

If they want the full fingerprint:

1. Package the evidence (no raw transcripts reach you, only a compact bundle per
   rig):

   ```
   python3 adapters/claude-code/fingerprint_evidence.py \
       --snapshot <snap-dir> --out <snap-dir>/fingerprint-evidence.json
   ```

2. **Classify distinct rigs, not sessions.** The bundle is keyed by rig
   (`engine/routing/effort`); every session sharing a skeleton is one rig, so you
   classify each rig once. This is the dedup that keeps the cost a fraction of a
   percent of weekly output. Run the cascade cheap-first: Haiku triages the
   obvious rigs, escalate an ambiguous one to Sonnet, Opus only if still unclear.
   For each rig, read its `skills` / `bash` / `subagent_tasks` evidence and pick
   one accepted-term value per dimension from docs/taxonomy.md (e.g. review regime
   in none / automated / agentic review pass / sweeps / cross-model / spec +
   acceptance / manual). Cost-gate exactly like the misery layer: above ~1% of
   weekly output, show the operator the ratio and ask before spending.

3. Write labels only (no raw text; operator-correctable) to
   `<snap-dir>/fingerprint-labels.json`:

   ```
   { "schema": "agent-dyno/fingerprint-labels@1",
     "rigs": { "delegate/none/high": { "fine_topology": "orchestrator-workers",
       "review_regime": "agentic review pass", "knowledge_practice": "skills" } } }
   ```

4. Re-run the driver (step 3). It finds the cache alongside the snapshot (or pass
   `--labels <path>`), fills the three slots of `fingerprint`, and exposes
   `by_review_regime` / `by_knowledge_practice` slices.

## 4. Present the surface, and only the surface

The driver already wrote it: show `report.md`. It is three things and nothing
else, so present those three and stop:

1. **The topline** (`topline.eq`): one number, `surviving functionality
   (decision points) per Mtok output`, higher is better. This is the meter.
2. **The one lever** (`lever`): the single tweak with the largest predicted gain,
   in plain language, with the predicted new topline. If `lever` is null, say
   they are at the frontier for their shape and there is nothing to suggest; never
   invent a lever.
3. **The measure line** (`measure`, present only with `--baseline`): the actual
   move since last run, beside what was predicted. This is the loop: tweak,
   re-run, see if it moved.
4. **EQ over time** (`timeline`, and the chart in `report.html`): the weekly EQ
   curve with the operator's own fingerprint changes flagged on it, so a move
   ties to a change they made, not to noise. Point them at `report.html` for the
   chart; the compact version is already in `report.md`.

Do **not** narrate the vector, the same-shape cells, the claims, or the
confounds. That is the machinery; it lives in `report.json` for anyone who asks
to see the derivation. Survival is not value; if you add a caveat, that is the
one. Keep it short.

## 5. Contribute (opt-in, with explicit consent)

Offer to emit an anonymized entry (engine fingerprint + vector only; no
identities, repo names, or code) that the operator can PR into
`frontier/reference-frontier.json`. Follow `skills/dyno-contribute/SKILL.md`.
Never submit without explicit consent.

## Deferred (not yet turn-key)

The git-side per-engine survival cut (which engine's *committed* lines lasted, by
effort) is v2 and not in `report.json` yet. If the operator wants it now, run
`core/horizon_attribute.py --repo <repo> --snapshot <snap> --since <window>` per
repo by hand, and label it as the durable-horizon cut, distinct from the
same-session waste in the vector.
