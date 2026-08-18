# Nostr as a federation transport (adopted, opt-in)

Status: ADOPTED as an opt-in live-mesh transport (owner decision, 2026-08-17), additive to
the file model, which stays the default. The aggregate-as-event path is proven end to end
(`docs/spikes/nostr-aggregate-spike.md`); the build sequence is the roadmap at the end of
this note. `federation.md` carries the posture change (file path keyless; opt-in keys for the
mesh; still no wallet, no chain). This note records why Nostr fits, the shape, the one real
tension and its resolution, and the hard-won lessons reused from three sibling projects that
went Nostr-first (`ready`, `dontguess`, `nostr-relay`/moot.pub).

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

## The public relay is read-open, write-curated (and that is correct)

The public relay (`relay.3dl.network`) admits writes by allowlist. This is not a problem to
work around, it is the curated-public-frontier invariant enforced at the wire:

- **Reads are open.** Anyone folds the public board with no key; `vibrant.3dl.dev` needs no
  identity to render.
- **Only the curator writes the public board.** Exactly one key is admitted: the 3dl frontier
  owner key. The public frontier is 3dl's board, curated (`governance.md`), so curation
  happens at write, which is also the sybil tax: a free npub cannot flood a locked relay.
- **Contributors reach the public board through curation, unchanged.** They submit (a PR with
  a Tier-2/3 proof, or publish to their own relay) and 3dl republishes the accepted aggregate
  to the board with its admitted key. The only change from the file era is the publish target.
- **Teams never touch the public relay.** A team runs its own relay (open or its own
  allowlist), publishes and folds there; `vibrant-federate` takes any `--relay`. No dependency
  on the 3dl relay's policy.

An open public relay would be the actual bug: unbounded self-publish is the permissionless
spam/sybil problem the sibling projects deferred. Locked write plus open read is the design
working, and it means only the single curator key ever needs admission.

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

## Adoption roadmap

Adopted, staged so each step is provable and the file model never regresses:

- **Stage 0, aggregate-as-event (DONE).** `summarize` output published as addressable
  kind-30078 events; `leaderboard/vibrant.html?relay=` folds them. All acceptance passed,
  including latest-wins-per-shape (`docs/spikes/nostr-aggregate-spike.md`).
- **Stage 1, owner-rooted grants (NEXT, scoped).** A team frontier is a board; only
  owner-granted npubs contribute; the client re-verifies. Scoped in
  `docs/spikes/nostr-grants-spike.md`.
- **Stage 2, our own signer + the Nostr hoistable (core DONE).** Built separately in
  `nostr-emit` (a reusable repo, so Vibrant's adapters carry no general Nostr program). The
  deterministic core, `nostr_event.py`, is NIP-01 canonical id plus BIP-340 sign/verify,
  stdlib only, no network, landed source-first and validated against `nak` in both directions.
  Per the hoistable philosophy the code stops at the invariant checksum: standing up a relay,
  publishing, and folding are a skill (`hoist-nostr.skill.md`) the receiver's agent runs, not
  a program we ship. Proven end to end (2026-08-17): `nostr_event.py` signed three `summarize`
  aggregates, they were published as-given to a clean LAN relay, the relay validated and
  accepted our BIP-340 signatures, and the leaderboard folded them, no `nak` signing anywhere
  in the chain. Stage 2 done.
- **Stage 3, skill wiring (DONE).** `skills/vibrant-federate` drives the whole mesh with no
  command line for the operator: the agent mints the identity (`keys.py`), produces the
  aggregate (`summarize`), signs it (`nostr_event.py`), publishes it (`relay_io.py`, a stdlib
  WebSocket, no `nak`), and folds it, asking the operator only for values it cannot derive (a
  relay, a board). It covers contribute, start-board, grant/revoke, and view;
  `vibrant-contribute` hands off to it for the live push. The file path stays the zero-setup
  default. Verified end to end against a LAN relay with zero external tools.
- **Stage 4, the public frontier as a board, hosted at `vibrant.3dl.dev`.** Feasible on
  infrastructure that already exists; the three parts:
  1. **Relay: `wss://relay.3dl.network`** (the existing managed-cert Azure relay, reachable
     over `wss` from the stdlib transport). A hosted `https` page can only open `wss`, never
     the LAN `ws://` relays, so the public board must live here.
  2. **Board:** a 3dl owner key publishes the public board (kind 30301) and its aggregates to
     that relay with `vibrant-federate` (`start-board` then `contribute`, `--relay wss://relay.3dl.network`).
     The relay's write policy is allowlisted, so the owner key needs write access; curation is
     the owner granting contributors, as `CLAUDE.md` describes. Proof tiers ride on the event;
     reproduction stays the sybil tax.
  3. **Page:** serve `leaderboard/vibrant.html` at `vibrant.3dl.dev`, a subdomain on the same
     static hosting as `3dl.dev` (the `website` repo; `forge.3dl.dev` is already a sibling
     subdomain), with a CNAME in the DNS zone. In that hosted copy set `DEFAULT_RELAY =
     "wss://relay.3dl.network"` and `DEFAULT_BOARD = "<board coord>"` so a visitor with no
     query params folds the public board; the 15s fold cap tolerates the relay's scale-to-zero
     cold start. Parts 2 and 3 are externally-visible ops (a public relay write, DNS, a
     deploy), owner-run; the page code (baked defaults + cold-start tolerance) is done.

  **Launch status (2026-08-17):** the page is LIVE at `vibrant.3dl.dev` (GitHub Pages on
  `3dl-dev/vibrant`, `gh-pages` branch, DNS `vibrant.3dl.dev -> 3dl-dev.github.io`, HTTPS cert
  provisioning), baked to fold the board `30301:28e74283...:public` on `wss://relay.3dl.network`.
  It shows the seed frontier until the board is published. Remaining, owner-gated: admit the
  frontier owner key (pubkey `28e74283793831aa1563ef0ad0f21bbc8ca51f1e7b63ff71bd14a6b6fd0a31ee`,
  stored `~/.config/vibrant/frontier-owner.key`) to the relay's tenant write-allowlist, after
  which one `vibrant-federate` run publishes the board and the live page lights up with no redeploy.

Invariants held at every stage: the file is the default and stays keyless; the relay is a
cache, never the source of truth; only anonymized aggregates travel, never raw logs; no
wallet and no chain; trust stays the proof-tier ladder.
