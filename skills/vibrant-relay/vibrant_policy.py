#!/usr/bin/env python3
"""
vibrant_policy: a strfry write-policy plugin that turns a stock relay into a Vibrant relay.

strfry runs this per incoming event: one JSON request per line on stdin, one JSON result per
line on stdout ({"id":..., "action":"accept"|"reject", "msg":...}). It enforces the Vibrant
posture from docs/public-relay-cost-and-abuse.md: writes are OPEN (no author allowlist, so
anyone can share in one step), but three cheap, friction-free gates keep the relay from being a
spam dump or an open bill:

  1. Kind gate: only Vibrant kinds are accepted, so the relay never becomes a general dumping
     ground. Aggregates (30078), personal reports (30079), boards (30301), grants (39301),
     follow lists (3), and profiles (0).
  2. Size gate: an event may not exceed the per-kind cap (reports are larger than aggregates).
  3. Proof-of-work gate (NIP-13): the event id must carry at least POW_BITS leading zero bits.
     A few seconds of the sharer's own CPU, once, invisible in a skill flow, but it prices a
     flood out of existence, this replaces the allowlist as the anti-flood gate.

Addressable-replace (one event per shape per author) is native to strfry for 3xxxx kinds, so
per-author storage is bounded regardless of how often someone shares. Reads are open and
capped at the edge (see the deploy recipe).

Config via env: VIBRANT_POW_BITS (default 20), VIBRANT_MAX_AGG (default 8192),
VIBRANT_MAX_REPORT (default 262144). Python 3 stdlib only.
"""
import json
import os
import sys

VIBRANT_KINDS = {0, 3, 30078, 30079, 30301, 39301}
REPORT_KIND = 30079
POW_BITS = int(os.environ.get("VIBRANT_POW_BITS", "20"))
MAX_AGG = int(os.environ.get("VIBRANT_MAX_AGG", "8192"))
MAX_REPORT = int(os.environ.get("VIBRANT_MAX_REPORT", "262144"))


def leading_zero_bits(hex_id):
    """NIP-13 difficulty: count leading zero BITS of the 32-byte event id."""
    try:
        b = bytes.fromhex(hex_id)
    except ValueError:
        return -1
    n = 0
    for byte in b:
        if byte == 0:
            n += 8
            continue
        n += 8 - byte.bit_length()
        break
    return n


def decide(event):
    """Return (action, msg) for one event. Pure, so it is unit-testable without a relay."""
    kind = event.get("kind")
    if kind not in VIBRANT_KINDS:
        return "reject", "blocked: this relay only carries Vibrant events"
    size = len(json.dumps(event, separators=(",", ":")))
    cap = MAX_REPORT if kind == REPORT_KIND else MAX_AGG
    if size > cap:
        return "reject", f"blocked: event too large ({size} > {cap} for kind {kind})"
    # profiles and follow lists (identity/grouping) do not need PoW; content kinds do.
    if kind in (0, 3):
        return "accept", ""
    bits = leading_zero_bits(event.get("id", ""))
    if bits < POW_BITS:
        return "reject", f"blocked: insufficient proof-of-work ({bits} < {POW_BITS} bits)"
    return "accept", ""


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        # strfry sends {"type":"new"|"lookback",...,"event":{...}}; only gate new writes.
        event = req.get("event") or {}
        eid = event.get("id", "")
        if req.get("type") not in ("new", None):
            sys.stdout.write(json.dumps({"id": eid, "action": "accept"}) + "\n")
        else:
            action, msg = decide(event)
            out = {"id": eid, "action": action}
            if msg:
                out["msg"] = msg
            sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
