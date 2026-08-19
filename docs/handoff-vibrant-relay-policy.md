# Handoff: flip the Vibrant relay from allowlist to open + proof-of-work

For the `nostr-relay` agent. Goal: make the public Vibrant relay accept writes from **anyone**,
gated only by kind + size + a small proof-of-work, so a user can share their result in one step.
The app (`vibrant.3dl.dev`) and the frontier already assume this: grouping is by following
(curation is at the viewer), so the relay does NOT need an author allowlist. The allowlist is
what is blocking ignition right now, a fresh key bounces with "not admitted to this relay's
tenant write-allowlist".

## The policy to implement (canonical spec)

The reference implementation is a strfry write-policy at
`~/projects/nostr-emit/relay/vibrant_policy.py` (pure `decide(event)`, unit-tested). Implement
the SAME logic. For the `vibrant` tenant on the cosmos/khatru relay this is a `RejectEvent`
policy, NOT a strfry plugin, but the rules are identical:

1. **Open writes.** REMOVE the author write-allowlist AND the forgemeter prepaid-balance gate
   for the `vibrant` tenant. Neither should gate writes; they contradict one-step sharing.
2. **Kind gate.** Accept only these kinds; reject anything else with "this relay only carries
   Vibrant events":
   - `30078` aggregate, `30079` personal report, `30301` board, `39301` grant (content kinds)
   - `0` profile, `3` follow list (identity / grouping kinds)
3. **Size gate.** Reject over the per-kind cap: `30079` (reports) up to 262144 bytes; all other
   Vibrant kinds up to 8192 bytes.
4. **Proof-of-work gate (NIP-13).** For the CONTENT kinds (30078/30079/30301/39301), require the
   event id to carry at least **20 leading zero bits** (count leading zero bits of the 32-byte
   id). Reject below the floor with "insufficient proof-of-work (N < 20 bits)". The identity /
   grouping kinds (0, 3) are EXEMPT (no PoW), so following and profiles stay frictionless.
5. **Addressable-replace** stays as-is: 3xxxx kinds are replaceable per `(author, kind, d)`, so
   per-author storage is bounded however often someone shares. No change needed.

Difficulty and caps should be config/env, matching the reference: `VIBRANT_POW_BITS=20`,
`VIBRANT_MAX_AGG=8192`, `VIBRANT_MAX_REPORT=262144`.

## Two ways to ship it (pick one)

- **A. In place on `relay.3dl.network` (khatru/cosmos).** Add the policy above as a `RejectEvent`
  func for the `vibrant` tenant and remove that tenant's allowlist + balance gate. One relay,
  keeps the existing DNS/TLS. This is the smaller change if we want a single relay. Note: the
  key-admission machinery (and the stranded `0361d14` env-var-permanence fix) becomes irrelevant
  for the `vibrant` tenant under open+PoW, nothing needs admitting anymore.
- **B. A dedicated Vibrant relay from the proven recipe.** `~/projects/nostr-emit/relay/` is a
  hoistable strfry + `vibrant_policy.py`, already built and graded in a container. Stand it up on
  a cloud host with a TLS front (Caddy/Front Door) for `wss://`, point DNS (e.g.
  `relay.vibrant.3dl.dev`) at it, and set `vibrant.3dl.dev`'s baked `DEFAULT_RELAY` to it. Fully
  isolated from the other tenants; the policy is drop-in and needs no re-implementation.

Recommendation: **B if you want isolation and the already-proven policy with zero re-impl; A if
you want to keep one relay.** Either way the acceptance test below is the gate.

## Keep the abuse controls (reads)

Open writes do not mean an open bill. Keep / add:
- Reads open, fronted by an edge **per-IP rate limit** (Front Door) + connection caps.
- A **hard Cosmos RU/s ceiling + Azure budget hard cap**, so a read flood degrades to bounded
  429s, never an open bill. (The dataset a view folds is tiny.)
- The NIP-11 caps already advertised (`max_limit` 500, `max_subscriptions`, `max_filters`).

Writes are bounded by the PoW (compute cost per event) + addressable-replace (storage), so the
flood surface is closed without an allowlist.

## Acceptance test (run against the deployed relay)

Use the stdlib tools in `~/projects/nostr-emit` (no installs). `$R` = the relay's ws/wss URL:

```
NE=~/projects/nostr-emit
SK=$(python3 $NE/keys.py gen)
AGG='{"id":"summary-solo-high","engine":"solo","vector":{"dollars_per_survkb":1.31}}'

# (a) valid aggregate WITH pow -> ok:true, and round-trips
python3 $NE/nostr_event.py --sec "$SK" --kind 30078 --content "$AGG" \
  --tag d=summary-solo-high --tag t=vibrant-aggregate --pow 20 | python3 $NE/relay_io.py publish "$R"
python3 $NE/relay_io.py query "$R" '{"kinds":[30078],"#d":["summary-solo-high"]}'   # returns it

# (b) same WITHOUT pow -> ok:false "insufficient proof-of-work"
python3 $NE/nostr_event.py --sec "$SK" --kind 30078 --content "$AGG" \
  --tag d=summary-solo-high --tag t=vibrant-aggregate | python3 $NE/relay_io.py publish "$R"

# (c) non-Vibrant kind WITH pow -> ok:false "only carries Vibrant events"
python3 $NE/nostr_event.py --sec "$SK" --kind 1 --content spam --pow 20 | python3 $NE/relay_io.py publish "$R"

# (d) follow list (valid pubkey), no pow -> ok:true
python3 $NE/nostr_event.py --sec "$SK" --kind 3 --content '' \
  --tag p="$(python3 $NE/keys.py pub "$SK")" | python3 $NE/relay_io.py publish "$R"
```

Pass = (a) and (d) ok:true, (a) round-trips; (b) and (c) ok:false with the stated reasons. This
is exactly the grade the `vibrant-relay` hoist skill runs, and it is the same behavior already
proven against the containerized strfry build.

## Client side (already handled on our end)

The publisher mines the PoW: `nostr_event.py --pow 20` (a few seconds, once), and the
`vibrant-federate` skill passes it on publish, so real sharers meet the floor automatically and
never think about it. When you set a different `VIBRANT_POW_BITS`, tell us so the skill matches.
