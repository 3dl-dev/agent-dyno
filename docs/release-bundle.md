# Vibrant release bundle

One bundle that takes an operator from "how efficient is my setup?" all the way to a shared,
grouped, optionally self-hosted frontier, with a wizard so they never have to know which piece
to reach for or that any of it runs on Nostr.

## The front door

**`vibrant-wizard`** works out what the operator needs in a couple of plain questions and routes
to the right component below, recommending rather than listing. Everything else is reachable
directly too, but the wizard is where a new user starts. It speaks in outcomes; the words relay,
key, npub, kind never reach the operator.

## Components

| skill | what it does | status |
|-------|--------------|--------|
| **vibrant-wizard** | interactive front door: figures out the fit and routes | built |
| **vibrant-report** | measure your setup from your own logs + git survival, nothing uploaded | shipped, run on real data |
| **vibrant-dynamometer** | settle solo-vs-orchestration on identical terrain (removes the difficulty confound) | shipped, real run recorded (`dyno-result.md`) |
| **vibrant-federate** | share your anonymized roll-up in one step; team/company grouping by following; publish your full report to a private link | shipped, proven e2e on prod |
| **vibrant-relay** (`nostr-emit/relay`) | self-host the frontier: a PoW-gated, Vibrant-only relay, one recipe for local / private / cloud / public | shipped, container-proven |

Supporting tools (not user-facing, the skills lean on them): the stdlib `nostr-emit` trio
(`keys.py`, `nostr_event.py`, `relay_io.py`) for identity / signing / transport, the report
driver and adapters, and the write-policy (`vibrant_policy.py`).

## The journeys the bundle covers

- **Measure me.** wizard → `vibrant-report`. Local, nothing shared. The default first step.
- **Is orchestration worth it?** wizard → `vibrant-dynamometer`. One task, every engine, on
  identical terrain; the honest arbiter over the observational confound.
- **Compare and share.** wizard → report → `vibrant-federate`. See yourself on the public
  frontier and share your anonymized roll-up in one step (opt-in; only ratios + counts travel).
- **My team / company.** wizard → `vibrant-federate` team frontier. Grouping is following:
  individual / team / company are the same mechanism, different follow-set.
- **Private / self-hosted.** wizard → `vibrant-relay` + `vibrant-federate`. Their own host,
  nothing on shared infrastructure.

## Distribution

Two channels, same content:

- **Claude Code plugin marketplace:** ship the `skills/` set as a marketplace so users
  `/plugin install vibrant` and get the wizard + all components. (Packaging step: a
  `.claude-plugin/marketplace.json` listing the skills; the relay ships its hoist recipe.)
- **skillc self-building files** for portability: the audit-style skills compile to one-file
  self-building artifacts that rebuild and self-grade on any receiver (proven for the frontier
  aggregate and the confound audit). Behavioral pieces travel this way; the infra pieces (relay)
  travel as their hoist recipe.

## Release checklist

- [x] Wizard front door (`vibrant-wizard`).
- [x] Report, dynamometer, federate, relay all shipped and individually proven.
- [x] Measurement validity closed on real data (real ground truth + the selection confound
      named from the operator's own numbers; the dyno is the fixed-task arbiter).
- [x] Package `skills/` as a `.claude-plugin` marketplace (one `/plugin install vibrant`), tools vendored.
- [ ] A dynamometer task suite spanning sizes (map where each engine wins, not just small).
- [ ] End-to-end wizard walkthrough graded in a clean session (the next ouroboros).
