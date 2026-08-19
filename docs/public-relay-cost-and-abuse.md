# Hosting the public relay: cost, and making it un-abusable

The public frontier at `vibrant.3dl.dev` folds from `wss://relay.3dl.network` (an Azure
Container Apps + Cosmos DB relay, `nostr-relay`). This note sizes the cost and, more
importantly, argues why the public frontier is hard to abuse, and closes the gaps that remain.

## The one fact that makes it safe: writes are curated

The public frontier board is **write-allowlisted**: only the curator key
(`tenant:vibrant`) may publish to it, and even an admitted key is gated by a **prepaid
balance** (the forgemeter `BalanceMicro`, which bounces writes with "tenant prepaid balance is
depleted" at zero). So an attacker cannot write to the public board at all: no fake entries, no
flood, no storage blowup. Curation-at-write is the anti-abuse, and it is already in place.

That collapses the abuse surface to **reads only**. Everything below follows from that.

## Cost

- **Scale-to-zero** (`minReplicas=0`): idle cost is essentially the Cosmos floor, not compute.
  Compute spins up on the first read after idle (~12s cold start, which the page tolerates).
- **Tiny curated dataset:** the frontier is a handful of addressable events (aggregates,
  the board, grants), each REPLACED on re-publish, not appended. Storage is kilobytes and
  bounded; a full scan is cheap.
- The `~$78/mo` figure in `nostr-relay/docs/bench` was a heavier multi-project workload
  (ready + dontguess traffic). The frontier ALONE is far lighter: realistically single-digit
  to low-double-digit dollars a month, dominated by the Cosmos minimum, with compute only on
  actual reads. The only thing that can amplify cost is a read flood, addressed next.

## The remaining surface: read DoS, and how to cap it

Reads are open (anyone folds the board with no key, by design). With scale-to-zero, a read
flood spins compute and burns Cosmos request units (RU), so the failure mode is a **bill**, not
a breach. Bound it so the worst case is self-limiting:

1. **Front the relay with Azure Front Door + WAF:** per-IP rate limit (e.g. 60 req/min),
   connection caps, and geo/bot rules. This is the primary read-flood throttle and it lives at
   the edge, not in the relay code.
2. **Hard Cosmos ceiling + budget alarm:** cap autoscale RU/s and set an Azure budget with a
   hard spend cap. Under a flood the relay then returns 429s and degrades, instead of running
   up an open-ended bill. A read-DoS becomes a bounded, self-limiting event.
3. **Keep the NIP-11 caps** already advertised: `max_subscriptions` 200, `max_filters` 200,
   `max_limit` 500, `max_message_length` 512000. They bound per-connection work; the small
   dataset bounds per-query scan.
4. **Reject broad unfiltered REQs** (or cap their scan): the frontier only needs
   `kinds:[30078,30301,39301]` with a `#t`/`#a` filter, so an unfiltered whole-store REQ can be
   refused with a NOTICE rather than served.

With writes curated and reads rate-limited + RU-capped, there is no un-bounded lever an
attacker can pull: they cannot write, and reads degrade to 429 under a hard ceiling.

## The real danger zone: personal reports

The one thing that would blow this open is letting **arbitrary users publish their personal
report** (`vibrant.3dl.dev/me`, kind 30079, ~82 KB each) to the public tenant. That is
un-curated, large, per-user writes, exactly the flood the allowlist prevents today. Do NOT put
personal reports on the public tenant. Two safe homes instead:

- **Users run their own relay** (the hoistable `nostr-relay`): their report, their relay, their
  cost. Zero shared-relay abuse surface. This is the preferred answer and the reason to ship a
  self-hostable relay.
- **A separate `personal` tenant** with strict per-key limits: one addressable report per key
  (replaced, not appended, so storage is bounded), a small NIP-13 proof-of-work on the write to
  price spam, and the prepaid-balance gate so writes are never free. Fund it per-user or cap it
  hard; never let it share the frontier tenant's balance.

The principle: the public tenant only ever carries the curator's small, replaced dataset. Any
per-user write goes to a relay the user owns, or a separately-gated tenant, never the frontier.

## Checklist (make it damn hard to abuse)

- [x] Public board writes: allowlisted, curator-only, balance-gated. (In place.)
- [ ] Reads: Azure Front Door per-IP rate limit + WAF + connection caps.
- [ ] Cosmos: hard RU/s ceiling + Azure budget hard cap + RU-spike alert (read-DoS signal).
- [ ] Reject unfiltered whole-store REQs on the public tenant.
- [x] Storage: addressable-only for curated kinds (replaced, bounded).
- [ ] Personal reports: never on the public tenant, own-relay or a PoW+balance personal tenant.
- [x] Scale-to-zero (idle cost ~0); accept the cold start.
- [ ] Balance-depletion alert (a write-side outage signal, as just seen with vibrant).

The four unchecked items are Azure-layer configuration (Front Door, budget, an RU cap) plus the
personal-report routing decision, not relay code. They turn "cheap and curated" into "cheap,
curated, and provably bounded under attack."
