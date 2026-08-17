# Nostr as a federation transport (proposal, not adopted)

Status: exploratory. `federation.md` is unchanged and remains the shipped design. This note
records why Nostr is a strong fit for Vibrant's federation, a proposed shape, the one real
tension it creates, and the hard-won lessons to reuse from three sibling projects that
already went Nostr-first (`ready`, `dontguess`, `nostr-relay`/moot.pub). Adopting it is a
posture decision, reserved.

## Why it fits

Vibrant's federation is already "many frontiers, a tree by choice, never one central board"
(`federation.md`). A user owns a file; teams roll up by hand; nothing auto-shares. Nostr is
the same shape made live instead of by-hand, and its three properties map one-to-one onto
what we already want:

- **Users own their data.** A contributor signs their own aggregate with their own key and
  publishes it; there is no central service holding it, and they can stop or supersede it at
  will. This is our self-owned ethos, enforced by construction rather than by policy.
- **Groups form, federated or not.** A team frontier is an owner-rooted group; two frontiers
  federate bilaterally by choice. That is exactly our upward, opt-in tree, minus the manual
  PR.
- **No central server.** A frontier stops being a file someone has to host and PR against,
  and becomes an ownerless mesh the viewer folds.

## The unlock: we federate aggregates, not raw logs

The single hardest problem in the prior projects was **content confidentiality**: they
publish raw signed work items or inference artifacts, so they needed envelope encryption,
per-board content-encryption keys, NIP-44 wrapping, epoch rotation on revoke, and they still
accept that the whole work graph leaks to any relay query, with the operator seeing all
plaintext as a permanent trust model (`dontguess/docs/design/content-confidentiality-envelope-541.md`,
`ready/docs/design/confidential-boards-envelope.md`).

**Vibrant has none of that problem.** `core/frontier.py summarize` already emits exactly one
anonymized aggregate per rig shape: a median vector plus support counts, with a k-anonymity
floor, no ids, no repo names, no technique prose, no identity. That aggregate is *meant* to
be public. So the Nostr payload is the summary object we already produce, and we can **skip
encryption entirely**: there is no CEK, no forward-secrecy blast radius, no key-custody
threat model, no graph-metadata leak to accept, because the graph is the point. The prior
projects paid for confidentiality we do not need.

## Proposed shape

- **Event = one anonymized frontier aggregate.** The `summarize` output for one shape:
  shape id, median efficiency vector, support counts, and its proof tier. Nothing else.
- **Addressable (parameterized-replaceable) kind, keyed by `(author, shape-id)`**, so the
  latest aggregate per rig-shape per contributor wins for free, the way `dontguess`'s
  inventory projection (kind 30401) is an addressable, latest-wins view that is explicitly
  NOT the source of truth (`dontguess/docs/design/nostr-first-rebuild-decision.md`).
- **A group is a frontier board.** Reuse the owner-rooted model: a board-definition event is
  the team frontier, owner-signed role-grants say who may contribute, latest-grant-per-member
  wins, revocation is prospective. This is `ready`'s kind-30301 board + kind-39301 grant
  design (`ready/docs/design/nostr-identity-model.md`), which was reached to avoid
  web-of-trust. The public frontier is 3dl's board; curation is the owner merging what it
  trusts, which is what `CLAUDE.md` already describes.
- **Relays: 3dl runs one, teams run their own, solo stays a file.** We already operate relay
  infrastructure (moot.pub / `nostr-relay`). The relay is a **cache, never the source of
  truth**: the local frontier file stays authoritative, exactly as our design already treats
  it, and matches the prior invariant that the local log wins and the relay is only durability
  (`ready/docs/relay-runbook.md`).
- **Trust stays the proof-tier ladder.** An npub adds persistent, pseudonymous reputation for
  free, but the sybil tax remains reproduction (Tier 2/3). This is the correct answer: the
  prior sybil analysis concluded cost must bind to the *claim*, not to identity, because
  npubs are free, and that reproduction-as-cost is exactly Tier 3
  (`dontguess/docs/design/convergence-sybil-defense.md`).

## The one real tension

`federation.md` says, deliberately: "No keys, no wallet, no chain. A heavy identity
dependency would kill adoption." Nostr is keys plus relays. It is **not** a wallet or a chain
(there is no coin and no ledger), so half of that sentence is untouched, but the keys half is
a real change and must be handled carefully:

- **Keep the file default.** Solo and file-only users get keys and relays never; "a frontier
  is just a file" stays the zero-setup path. Mandating a relay for one user is, in the prior
  projects' own words, infrastructure fetish (`dontguess/docs/design/federation-modes.md`).
- **Nostr is an opt-in transport for groups**, chosen when a team wants live sync instead of
  PRs. Adoption is preserved because the friction is only paid by those who want the mesh.

Framed that way, Nostr does not replace the file model, it is a second surface over the same
aggregates, like the Slack/CI surfaces `federation.md` already anticipates.

## Lessons to reuse (paid for already, in the sibling repos)

- **Relay is a cache; the local file is truth.** Never gate a write on relay reachability;
  count and alarm every relay failure, never a silent nil.
- **Client re-verifies every event.** A relay allowlist is coarse anti-spam admission, never
  the trust authority; signature-validity is never admission
  (`ready/docs/design/nostr-identity-model.md`). All authority is derived from signed grants
  at read time.
- **Atomic key creation and identity-preserving migration.** Create keys temp-file to fsync
  to hard-link (not `O_EXCL`), migrate by copy never regenerate, and assert on startup that
  the loaded pubkey is in the derived trust set. Non-atomic creation and silent regeneration
  were both catastrophic there (`dontguess/pkg/identity/keyfile.go`,
  `ready/docs/design/nostr-identity-model.md`).
- **No total order on Nostr.** Fold order is an operator-assigned local sequence, not relay
  ingest order; bound any pending-antecedent buffer and make no trust decision about which
  orphan is "bad" (`dontguess/docs/design/relay-transport.md`).
- **One write choke point.** Route every wire write through a single guarded function, or an
  in-package caller reaches the wire and bypasses the checks (`ready`'s publishguard).
- **Never publish a plaintext content hash.** Even though our payloads are public, any dedup
  or shape key derived from private data must be a keyed HMAC or stay local, never a bare
  hash, which is a guess-confirmation and correlation oracle
  (`dontguess/docs/design/content-confidentiality-envelope-541.md`).
- **Measure the relay backend, do not trust projections.** Azure Table Storage failed the
  latency gate and Cosmos came in ~9x over its cost projection
  (`nostr-relay/docs/feasibility-stateless-core.md`). The only real relay exposure at our
  scale is the latency tail crossing client timeouts, not average latency.
- **Allowlisted relays that never send AUTH hang the client.** Default to no client-auth and
  deadline-bound reads (`dontguess/docs/design/nostr-first-client-ed2.md`).

## Deliberately NOT taken

- **Envelope encryption / CEK / forward secrecy.** Not needed: aggregates are anonymized and
  public by design. Adding it would import the prior projects' hardest, still-imperfect layer
  for no benefit.
- **Global permissionless convergence economics** (proof-of-cost burn, scrip, PAC weighting).
  Our sybil answer is reproduction, which is stronger for our case and already shipped.
- **Agent-level web-of-trust.** Rejected there as a "trust assumption dressed as
  trustlessness"; our owner-rooted board grants and proof tiers do the job.

## Reserved decision and smallest first step

Reserved to the owner: whether to adopt Nostr as an optional federation transport, and
whether that shifts the stated "no keys" posture in `federation.md` (proposed shift: "no
keys on the file path; opt-in keys for the live mesh").

If yes, the smallest honest first step is a spike: publish a single `summarize` aggregate as
an addressable event to the 3dl relay and render it in `leaderboard/vibrant.html` by folding
the relay instead of reading the file, with no encryption and no group grants yet. That
proves the aggregate-as-event path end to end before any identity or group machinery is
built.
