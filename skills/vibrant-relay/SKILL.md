---
name: vibrant-relay
description: Stand up a Vibrant relay on any target (local, a private team box, or a public cloud host) and grade it. Same recipe every avenue; the relay is a stock strfry configured for the Vibrant frontier (open writes, proof-of-work gated, Vibrant events only). Use for "run a Vibrant relay", "self-host the frontier", or "deploy the public relay".
argument-hint: [local | private | cloud] [--pow-bits 20]
---

# Vibrant relay (hoist recipe)

This is a recipe you (the agent) run in the receiver's session to stand a Vibrant relay up and
prove it works. It is a stock **strfry** plus the Vibrant write-policy: writes are OPEN (anyone
shares in one step, no allowlist), gated only by kind + size + a small proof-of-work. The same
recipe covers every avenue; only the host and the TLS front differ.

Grade honestly. Each step says what "worked" means. If a step cannot run here, say so and stop,
never fake a pass. Nothing user-facing here needs a command line from the operator.

## Files (this directory)

`Dockerfile`, `docker-compose.yml`, `vibrant.strfry.conf`, `vibrant_policy.py` (the policy),
and the bundled stdlib tools `keys.py`, `nostr_event.py`, `relay_io.py` (in this dir, used to grade).

## 1. Pick the avenue

- **local** (default): a relay on this machine for development or a solo user. `ws://localhost:7777`.
- **private**: same image on a team box; reachable on the LAN, optionally behind a TLS proxy
  for `wss://`. The team's view follows the team's keys; no public exposure.
- **cloud / public**: build the image, push it to a container host (a VM, Azure Container Apps,
  Fly, etc.), put a TLS front (Caddy / Front Door) in front for `wss://`, and point DNS at it.
  This is how the public frontier relay is run; it is the same relay, just hosted and fronted.

## 2. Stand it up

Preconditions: Docker (a container runtime). Confirm it, do not assume.

```
docker compose up -d --build          # from this directory
```

Worked = the container is running and the port answers a WebSocket upgrade. If the base image
`dockurr/strfry` is unavailable on the target, pick another strfry image and pass it:
`STRFRY_IMAGE=<image> docker compose build`. For cloud, build once and deploy the image to the
host; the config and policy travel in the image.

## 3. Grade it (the honest-grade self-test)

Run these with the sibling stdlib tools; `$R` is the relay's ws/wss URL. They are the same
checks the write-policy enforces, so passing them proves the relay is configured correctly.

```
NE="<this skill's dir>"                # the bundled tools sit beside this SKILL.md
SK=$(python3 $NE/keys.py gen)
AGG='{"id":"summary-solo-high","engine":"solo","vector":{"dollars_per_survkb":1.31}}'

# (a) a valid Vibrant aggregate WITH proof-of-work -> ACCEPTED, and round-trips
python3 $NE/nostr_event.py --sec "$SK" --kind 30078 --content "$AGG" \
  --tag d=summary-solo-high --tag t=vibrant-aggregate --pow 20 \
  | python3 $NE/relay_io.py publish "$R"        # expect {"ok": true}

# (b) the SAME without proof-of-work -> REJECTED (insufficient proof-of-work)
python3 $NE/nostr_event.py --sec "$SK" --kind 30078 --content "$AGG" \
  --tag d=summary-solo-high --tag t=vibrant-aggregate \
  | python3 $NE/relay_io.py publish "$R"        # expect ok:false, "insufficient proof-of-work"

# (c) a non-Vibrant kind (chat) even with PoW -> REJECTED (only Vibrant events)
python3 $NE/nostr_event.py --sec "$SK" --kind 1 --content spam --pow 20 \
  | python3 $NE/relay_io.py publish "$R"        # expect ok:false, "only carries Vibrant events"

# (d) a follow list (kind 3), no PoW -> ACCEPTED (identity/grouping needs no PoW).
# The `p` tag must be a real 32-byte hex pubkey (strfry validates tag shape before the policy).
python3 $NE/nostr_event.py --sec "$SK" --kind 3 --content '' --tag p="$(python3 $NE/keys.py pub "$SK")" \
  | python3 $NE/relay_io.py publish "$R"        # expect {"ok": true}
```

Worked = (a) and (d) return ok:true and (a) round-trips on a query; (b) and (c) return ok:false
with the stated reasons. Report which of (a)-(d) matched. A relay that accepts (b) or (c) is
mis-configured (the write-policy is not wired); say so rather than pass it.

## 4. Report

State the avenue, the relay URL, and the four grade results. For cloud, also report the TLS
front and DNS. The operator never typed a command; you ran it all, and you only ask for what
you cannot derive (a host, a domain).

## Notes

- **Open writes are the point:** do NOT add an author allowlist; the PoW + kind + size gates are
  the whole anti-abuse story (see `agent-dyno/docs/public-relay-cost-and-abuse.md`). Grouping is
  following, enforced by the viewer, not the relay.
- **Tune with env:** `VIBRANT_POW_BITS` (default 20) trades share-latency for flood-resistance;
  `VIBRANT_MAX_REPORT` bounds the `/me` payload. Reads should sit behind an edge rate-limit and a
  hard budget ceiling on a public host.
