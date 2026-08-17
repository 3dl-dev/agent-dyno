# Spike: owner-rooted write authority for a team frontier

The second spike for `federation-nostr.md`. The first proved an aggregate travels as an
event and folds. This one proves the group: only npubs an owner has granted may contribute
to a team frontier, and the leaderboard enforces it client-side, so a stranger cannot poison
a board by publishing to its relay. Still a spike: throwaway, no encryption, no UI.

## Goal

Given a team frontier identified by a board coordinate, the leaderboard folds ONLY aggregate
events whose author the board owner has granted, derives that grant set fresh from signed
events (never a config allowlist), and drops a contributor the owner revokes.

## Non-goals (out)

- No encryption (aggregates stay public).
- No grant hierarchy beyond owner and contributor (no maintainers minting maintainers yet).
- No retroactive `from=T` revocation, no multi-owner, no invite tokens.
- No new signer: `nak` still publishes; only the read path grows.

## The model (reused from `ready`, owner-rooted, not web-of-trust)

- **A board is the team frontier.** A board-definition event, kind `30301`, addressable at
  `30301:<owner-pubkey>:<d>`; the owner's key is the trust root. This is exactly `ready`'s
  board model (`ready/docs/design/nostr-identity-model.md`).
- **A grant says who may contribute.** An owner-signed role-grant event, kind `39301`,
  addressable per `(board, grantee)` so the latest grant per grantee wins for free: role
  `contributor` admits, role `revoked` removes. Only the board owner's grants count;
  everyone else's are ignored at derivation (the escalation cap).
- **The client re-verifies.** The leaderboard derives the granted set from the board and its
  grants at read time and folds only aggregates whose `pubkey` is in it. A relay allowlist,
  if any, is coarse anti-spam, never the authority (`ready/docs/design/nostr-identity-model.md`).

## The read path (the only code)

Extend `foldRelay` with an optional board coordinate, gated by a `?board=<30301:pub:d>` query
param alongside `?relay=`:

1. REQ the board event (`kinds:[30301]`, author + d from the coord) and its grants
   (`kinds:[39301]`, `#a` = the board coord). The board author is implicitly granted.
2. Derive `granted` = { owner } union { grantee : latest grant for that grantee has role
   `contributor` }, minus grantees whose latest grant is `revoked`.
3. REQ the aggregates (`kinds:[30078]`, `#t` `vibrant-aggregate`) as today, but keep an event
   only if `ev.pubkey in granted`. Everything else unchanged.

About 25 lines added to the existing `foldRelay`, no library. With no `?board=`, behavior is
exactly the current spike (any author renders), so this is additive.

## Acceptance

Run against the LAN relay used in the first spike. With owner key O and keys A, B:

1. O publishes a board and a `contributor` grant for A. A publishes an aggregate.
   `vibrant.html?relay=..&board=..` renders A's row.
2. B (never granted) publishes an aggregate. It does NOT render: ungranted authors are
   dropped, so a stranger cannot post to the board.
3. O publishes a `revoked` grant for A (latest-wins). On reload, A's row disappears.
4. Without `?board=`, the board renders every author (the first spike's behavior), unchanged.

## What it derisks

- Owner-rooted admission works client-side over Nostr, so a public relay does not have to be
  trusted to gate writes: the exact property that lets 3dl run one relay for many teams.
- Grant derivation is latest-wins-per-grantee, a plain fold, matching the addressable-event
  pattern the first spike already proved.

## Left for later (not this spike)

- Maintainer delegation and the escalation cap in full, invite tokens, retroactive revocation.
- Our own stdlib signer and a minimal WS publisher (the Nostr hoistable) replacing `nak`.
- Confidentiality: not needed while frontiers carry only anonymized aggregates.

## Effort

About a day: ~25 lines on `foldRelay` for grant derivation and author filtering, plus `nak`
one-liners to publish the board, grants, and test aggregates from three throwaway keys.

## Result (executed 2026-08-17)

Ran against the LAN relay `ws://192.168.2.40:7777` with three throwaway keys (owner O,
contributor A, rogue B). `foldRelay` gained board mode (gated by `?board=<30301:owner:d>`):
it REQs the owner's kind-39301 grants alongside the kind-30078 aggregates, derives the granted
set (owner plus contributors, latest grant per grantee wins), and folds only aggregates whose
author is granted. All four acceptance criteria passed:

1. O published the board and a `contributor` grant for A; A published the frontier. The board
   rendered A's three rows, with a context line naming the trust model.
2. B (never granted) published an aggregate with a dominating fake vector. In board mode it was
   DROPPED; in no-board mode the same event rendered as a false `pareto` leader, which is
   exactly the poisoning the board prevents.
3. O published a `revoked` grant for A (latest-wins). On reload the board found no granted
   authors and fell back to seed: A's contributions were gone.
4. Without `?board=`, every author rendered (Stage 0 behavior), unchanged.

The board-mode read path is committed (guarded behind `?board=`, so default behavior is
unchanged); the live e2e run is its verification. Derisked: owner-rooted admission enforced
client-side over Nostr, so a public relay need not be trusted to gate writes. This clears
Stage 1 of the adoption roadmap; Stage 2 (the stdlib signer / Nostr hoistable) is the next
build.
