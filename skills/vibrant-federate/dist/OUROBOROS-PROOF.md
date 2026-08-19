# Ouroboros proof: a compiled Vibrant skill, rebuilt and run end to end

`vibrant-frontier-share.selfbuild.SKILL.md` is a `skillc`-format self-building skill: it
carries the anonymize-into-a-public-aggregate definition, binds (the stdlib `nostr-emit`
signer + a relay), checks (no identity/repo/path/key; valid schema; honest tier; addressable
publish), build examples, and held-out acceptance examples, with the rebuild recipe stamped on
top.

Tested by handing the file, and nothing else, to a fresh clean-context agent (it knew nothing
of this project). It ran the embedded recipe and reported:

> Built. Build examples matched 2 of 2, acceptance score 1.0. Ready.

Then it used the skill on a NEW leaky input (a run whose note named a private repo
`initech/payroll`, a path `/home/bob/initech`, and an orchestrator `bob-fleet`):

- Produced the anonymized aggregate: repo, path, and operator name all dropped; only ratios +
  a generic technique traveled.
- Signed kind 30078, published to the relay (ok=true), and confirmed the event round-trips.
- Leaked nothing identifying; printed no key; handed back a `vibrant.3dl.dev` link.

It also noticed a stale `rogue-injected` event already on the relay and ignored it as untrusted
relay data, independently arriving at the read-open / verify-on-fold principle in
`docs/public-relay-cost-and-abuse.md`.

The loop closes: the skill-that-makes-skills produced a distributable file; the file rebuilt
and graded itself on a machine that had never seen it; and it ran the real publish end to end.
