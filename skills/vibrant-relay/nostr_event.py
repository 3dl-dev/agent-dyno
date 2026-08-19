#!/usr/bin/env python3
"""
nostr_event: the deterministic Nostr signing core (nostr_event.spec.md).

Turns a payload plus a secret key into a valid, signed NIP-01 event: the canonical
event id (sha256 over the fixed-order serialization) and a BIP-340 Schnorr signature.
Pure computation, Python 3 standard library only, no network. Relay I/O is the skill's
job, never this module's.
"""
import argparse
import hashlib
import json
import sys
import time

# secp256k1 domain parameters.
_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_Gx = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_Gy = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
_G = (_Gx, _Gy)


def _tagged_hash(tag, msg):
    t = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(t + t + msg).digest()


def _point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    if x1 == x2 and y1 == y2:
        lam = (3 * x1 * x1 * pow(2 * y1, _P - 2, _P)) % _P
    else:
        lam = ((y2 - y1) * pow(x2 - x1, _P - 2, _P)) % _P
    x3 = (lam * lam - x1 - x2) % _P
    y3 = (lam * (x1 - x3) - y1) % _P
    return (x3, y3)


def _point_mul(p, k):
    r = None
    while k:
        if k & 1:
            r = _point_add(r, p)
        p = _point_add(p, p)
        k >>= 1
    return r


def _has_even_y(p):
    return p[1] % 2 == 0


def _lift_x(x):
    if x >= _P:
        return None
    c = (pow(x, 3, _P) + 7) % _P
    y = pow(c, (_P + 1) // 4, _P)
    if pow(y, 2, _P) != c:
        return None
    return (x, y if y % 2 == 0 else _P - y)


def _b(x):  # 32-byte big-endian
    return x.to_bytes(32, "big")


def pubkey_from_seckey(seckey):
    d = int.from_bytes(seckey, "big")
    if not (1 <= d <= _N - 1):
        raise ValueError("secret key out of range")
    P = _point_mul(_G, d)
    return _b(P[0])


def schnorr_sign(msg, seckey, aux=b"\x00" * 32):
    if len(msg) != 32 or len(seckey) != 32 or len(aux) != 32:
        raise ValueError("msg, seckey, aux must be 32 bytes")
    d0 = int.from_bytes(seckey, "big")
    if not (1 <= d0 <= _N - 1):
        raise ValueError("secret key out of range")
    P = _point_mul(_G, d0)
    d = d0 if _has_even_y(P) else _N - d0
    t = bytes(a ^ b for a, b in zip(_b(d), _tagged_hash("BIP0340/aux", aux)))
    rand = _tagged_hash("BIP0340/nonce", t + _b(P[0]) + msg)
    k0 = int.from_bytes(rand, "big") % _N
    if k0 == 0:
        raise ValueError("nonce is zero (astronomically unlikely)")
    R = _point_mul(_G, k0)
    k = k0 if _has_even_y(R) else _N - k0
    e = int.from_bytes(
        _tagged_hash("BIP0340/challenge", _b(R[0]) + _b(P[0]) + msg), "big") % _N
    sig = _b(R[0]) + _b((k + e * d) % _N)
    if not schnorr_verify(msg, _b(P[0]), sig):
        raise ValueError("signing produced an invalid signature")
    return sig


def schnorr_verify(msg, pubkey, sig):
    if len(msg) != 32 or len(pubkey) != 32 or len(sig) != 64:
        return False
    P = _lift_x(int.from_bytes(pubkey, "big"))
    if P is None:
        return False
    r = int.from_bytes(sig[:32], "big")
    s = int.from_bytes(sig[32:], "big")
    if r >= _P or s >= _N:
        return False
    e = int.from_bytes(
        _tagged_hash("BIP0340/challenge", sig[:32] + pubkey + msg), "big") % _N
    R = _point_add(_point_mul(_G, s), _point_mul(P, _N - e))
    if R is None or not _has_even_y(R) or R[0] != r:
        return False
    return True


def event_id(pubkey_hex, created_at, kind, tags, content):
    ser = json.dumps([0, pubkey_hex, created_at, kind, tags, content],
                     separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(ser.encode("utf-8")).hexdigest()


def _leading_zero_bits(hex_id):
    """NIP-13 difficulty: leading zero BITS of the 32-byte event id."""
    b = bytes.fromhex(hex_id)
    n = 0
    for byte in b:
        if byte == 0:
            n += 8
            continue
        n += 8 - byte.bit_length()
        break
    return n


def mine_pow(pubkey_hex, created_at, kind, tags, content, bits):
    """Grind a NIP-13 nonce tag until the event id carries >= `bits` leading zero bits.
    Returns (tags_with_nonce, event_id). A few seconds at ~20 bits on one core."""
    base = [t for t in tags if not (t and t[0] == "nonce")]
    nonce = 0
    while True:
        trial = base + [["nonce", str(nonce), str(bits)]]
        eid = event_id(pubkey_hex, created_at, kind, trial, content)
        if _leading_zero_bits(eid) >= bits:
            return trial, eid
        nonce += 1


def signed_event(seckey_hex, kind, tags, content, created_at=None, pow_bits=0):
    seckey = bytes.fromhex(seckey_hex)
    pubkey_hex = pubkey_from_seckey(seckey).hex()
    if created_at is None:
        created_at = int(time.time())
    if pow_bits and pow_bits > 0:
        tags, eid = mine_pow(pubkey_hex, created_at, kind, tags, content, pow_bits)
    else:
        eid = event_id(pubkey_hex, created_at, kind, tags, content)
    sig = schnorr_sign(bytes.fromhex(eid), seckey).hex()
    return {"id": eid, "pubkey": pubkey_hex, "created_at": created_at,
            "kind": kind, "tags": tags, "content": content, "sig": sig}


def main():
    ap = argparse.ArgumentParser(description="sign a NIP-01 event (stdlib, no network)")
    ap.add_argument("--sec", required=True, help="secret key, 64 hex chars")
    ap.add_argument("--kind", type=int, required=True)
    ap.add_argument("--content", default="")
    ap.add_argument("--tag", action="append", default=[],
                    help="a tag as key=value (repeatable); becomes [key, value]")
    ap.add_argument("--created-at", type=int, default=None)
    ap.add_argument("--pow", type=int, default=0,
                    help="mine a NIP-13 nonce to this many leading zero bits before signing")
    args = ap.parse_args()
    tags = []
    for t in args.tag:
        k, _, v = t.partition("=")
        tags.append([k, v])
    ev = signed_event(args.sec, args.kind, tags, args.content, args.created_at, args.pow)
    sys.stdout.write(json.dumps(ev, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
