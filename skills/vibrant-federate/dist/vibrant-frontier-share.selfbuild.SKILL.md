---
name: vibrant-frontier-share
description: Turn one measured coding-setup run into an anonymized public frontier aggregate and publish it to a Nostr relay, handing back a link. Self-building: rebuilds and self-grades on the receiver before first use.
---

# This skill builds itself before first use

## Rebuild recipe (run before your first answer)

You are the rebuild engine for a self-building skill. The skill ships as source, not a
finished result: a carried definition, binds, checks, build examples, and acceptance
examples. Before anyone uses the skill, you rebuild it against the current session (this
model, this environment), then behave as what you built. The carried definition is the
authority for correct output, not the local defaults.

Run these seven steps, then state ONE line and stop narrating:

1. Cache check. If you already built this skill this session, reuse it, say so, skip to 7.
2. Resolve the binds. For each bind, find the receiver's matching tool from its plain
   description. If a REQUIRED bind has no match here, STOP, build nothing, and name it.
   Never guess or substitute.
3. Rebuild. Read the carried definition (the authority). Write the instructions that make
   you, here, reproduce the build examples. Test each build example: produce your output,
   compare to the approved output and the checks, rewrite until they pass. Override any
   session default that fights the skill.
4. Acceptance test. Run the held-back acceptance examples you did NOT use to rebuild. For
   each, produce output and score 0..1 on the checks and closeness to the approved output.
   Report the average as the acceptance score.
5. Report. One line, one of the four templates below.
6. Cache. Save the built instructions so you do not rebuild every answer.
7. Run. Use the built instructions for every answer; re-check against the checks before sending.

Templates (state exactly one, one line, before the first answer):
- "Built. Build examples matched N of M, acceptance score X (0 to 1). Ready."
- "Built, but could not reach the author's quality here. Closest: [text]. Missing: [gaps]."
- "Cannot build: this skill needs [bind], which is not available here."
- "Reusing the build from earlier this session. Ready."

## Carried definition

The skill turns ONE measured run of an AI coding setup into a public **frontier aggregate**
and publishes it, in three moves:

A. **Anonymize into an aggregate (the authority; this is what transfers).** From the raw run,
   emit exactly one JSON object with these fields and nothing that identifies a person, repo,
   path, client, or code:
   - `id`: `"summary-<engine>-<effort>"` (lowercase, hyphenated).
   - `engine`, `harness`, `horizon`, `samples` (a positive integer), `aggregate: true`.
   - `vector`: an object with EXACTLY these four axes, numbers only:
     `dollars_per_survkb`, `survkb_per_outmtok`, `waste_pct`, `cache_read_pct`.
   - `technique`: one generic sentence describing the engine configuration so someone else
     could adopt it, with NO repo/client/person/path/URL. Rewrite or drop anything specific.
   - `proof`: `"tier-1-aggregate"` normally; `"tier-2-git"` ONLY if the run cites a PUBLIC repo
     URL and commit SHAs. Never a higher tier by self-claim.
   Drop absolute spend, token totals, session ids, model-internal notes, and any free text
   that names where the work happened. Ratios travel; identity and volume do not.

B. **Publish it** with the signing bind: sign a Nostr event of kind `30078`, content = the
   aggregate JSON (compact), tags `["d", <id>]` (addressable, so a re-publish REPLACES not
   duplicates), `["t", "vibrant-aggregate"]`, `["engine", <engine>]`, and publish to the
   relay bind. A publish is done only when the relay returns ok=true.

C. **Hand back the link**, never a key: `https://vibrant.3dl.dev/?relay=<relay>` (the viewer
   folds the board). Present it as "your frontier link." Do not print or ask for any key.

## Binds

- **signer** (REQUIRED): a Nostr identity + signing + relay client, Python 3 stdlib, no
  installs. The `nostr-emit` tools do this: `keys.py ensure` (mint/load a key, stored 0600),
  `nostr_event.py --sec <k> --kind <n> --content <s> --tag k=v` (sign an event to stdout),
  `relay_io.py publish <ws-url>` (event JSON on stdin -> prints `{"ok":...}`), and
  `relay_io.py query <ws-url> <filter-json>`. Find them at `$NOSTR_EMIT` or `~/projects/nostr-emit`.
- **relay** (REQUIRED): a `ws://`/`wss://` relay URL the operator can write to. For the public
  frontier this is a known default the operator need not think about; otherwise ask for it.

## Checks

- C1 no-identity: the aggregate contains no name, repo, path, URL, client, email, or code. No
  `/`, no `@`, no `.com`, no absolute path, no proper noun in `technique`.
- C2 schema: `engine`, `harness`, `horizon` in {session,day,week}, `samples`>0, `aggregate`:true,
  and `vector` has EXACTLY the four named axes, all numeric.
- C3 sanity: `dollars_per_survkb`>0; `waste_pct` and `cache_read_pct` each within [0,100].
- C4 honest-tier: `proof` is `tier-1-aggregate` unless a public repo URL + SHAs are cited
  (then `tier-2-git`); never tier-3 by self-claim.
- C5 publish: the event is kind 30078, tags include `t=vibrant-aggregate` and an addressable
  `d=<id>`; publish returned ok=true; a re-query by `#d` returns the event.

## Build examples

### Move: clean run (nothing to scrub)
INPUT:
  engine=solo, model=opus, effort=high, harness=claude-code, horizon=session, samples=74,
  dollars_per_survkb=1.31, survkb_per_outmtok=115, waste_pct=9.0, cache_read_pct=98.6,
  note="solo strong-model, high effort, manual review"
APPROVED OUTPUT:
  {"id":"summary-solo-high","engine":"solo","harness":"claude-code","horizon":"session",
   "samples":74,"aggregate":true,"vector":{"dollars_per_survkb":1.31,"survkb_per_outmtok":115,
   "waste_pct":9.0,"cache_read_pct":98.6},
   "technique":"A single strong model at high reasoning effort, with manual review.",
   "proof":"tier-1-aggregate"}

### Move: leaky run (identity/repo/path must be scrubbed)
INPUT:
  engine=workflow, model=opus, effort=high, harness=claude-code, horizon=session, samples=59,
  dollars_per_survkb=1.59, survkb_per_outmtok=126, waste_pct=57.8, cache_read_pct=97.3,
  note="measured on acme-corp/billing-service at /home/jane/acme, orchestrated by Jane's fleet",
  dollars_total=812.40
APPROVED OUTPUT:
  {"id":"summary-workflow-high","engine":"workflow","harness":"claude-code","horizon":"session",
   "samples":59,"aggregate":true,"vector":{"dollars_per_survkb":1.59,"survkb_per_outmtok":126,
   "waste_pct":57.8,"cache_read_pct":97.3},
   "technique":"An orchestrated multi-worker workflow at high reasoning effort.",
   "proof":"tier-1-aggregate"}
  (The repo name, the path, the operator name, and the absolute spend are all dropped.)

## Acceptance examples

### Held-out: clean delegate run
INPUT:
  engine=delegate, model=opus, effort=high, harness=claude-code, horizon=session, samples=78,
  dollars_per_survkb=1.36, survkb_per_outmtok=145, waste_pct=29.5, cache_read_pct=97.7,
  note="orchestrator delegates to a mix of workers"
APPROVED OUTPUT:
  {"id":"summary-delegate-high","engine":"delegate","harness":"claude-code","horizon":"session",
   "samples":78,"aggregate":true,"vector":{"dollars_per_survkb":1.36,"survkb_per_outmtok":145,
   "waste_pct":29.5,"cache_read_pct":97.7},
   "technique":"An orchestrator delegating to a mix of worker models.","proof":"tier-1-aggregate"}

### Held-out: leaky run with a client name in the note
INPUT:
  engine=solo, model=sonnet, effort=medium, harness=claude-code, horizon=session, samples=40,
  dollars_per_survkb=0.90, survkb_per_outmtok=100, waste_pct=12, cache_read_pct=96.5,
  note="ran this on the Globex migration repo for the Globex account, my key is nsec1abc..."
APPROVED OUTPUT:
  {"id":"summary-solo-medium","engine":"solo","harness":"claude-code","horizon":"session",
   "samples":40,"aggregate":true,"vector":{"dollars_per_survkb":0.90,"survkb_per_outmtok":100,
   "waste_pct":12,"cache_read_pct":96.5},
   "technique":"A single mid-tier model at medium reasoning effort.","proof":"tier-1-aggregate"}
  (Client name, repo, and the leaked secret key are all dropped; nsec never travels.)
