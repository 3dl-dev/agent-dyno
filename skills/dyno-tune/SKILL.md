---
name: dyno-tune
description: Position your setup on the efficiency frontier and recommend the next single change to your engine — you versus your own past self, and versus the opt-in community frontier. Reads your recent efficiency vector + fingerprint, finds the axis you trail, and suggests one concrete harness tweak. Use for "how do I make my setup more efficient".
argument-hint: [--since 30.days.ago] [--compare <prior>]
---

# Dyno tune

Read `docs/governance.md`: this is self-improvement, you against past-you and
against the shared frontier of *engine craft* — never a ranking of people, never
tied to product outcomes.

**Input:** $ARGUMENTS

## Steps

1. Run `dyno-report` for the recent window → the efficiency vector + fingerprint.
2. **Find the trailing axis** — where the engine is worst relative to the
   reference frontier (`frontier/reference-frontier.json`) or the operator's own
   best prior window (`--compare`).
3. **Recommend exactly one change**, concrete and mechanism-linked:
   - waste high under workflow → that model is a poor orchestrator; keep it solo
     or move it to leaf work (match model to role).
   - parasitic load high → widen waves, cut coordination rounds.
   - many mid-session model switches → each pays a cold-prefill tax; pick a model
     per session.
   - wide fan-out with low reached-edit% → subagents pay ~30k prefill and many
     never edit; narrow the wave.
   - low cache-read share → tighten context.
   - review regime unclear or all-manual → check whether the human fuel is buying
     horizon-survival, or whether sweeps/cross-model would buy it cheaper.
4. Show the projected move on the vector; re-measure next window (you vs you). One
   change at a time; name the trade-off if it costs another axis.

## Frontier etiquette

The frontier is engine-craft, opt-in, anonymized. Compare the operator's engine
to it for direction. Never publish an individual's vector to a product-linked
ranking; that is the governance misuse.
