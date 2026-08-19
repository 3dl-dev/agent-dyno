#!/usr/bin/env python3
"""
keys: mint and load a Nostr identity, Python 3 standard library only.

A key is a random secp256k1 scalar. This mints one, stores it 0600, and reuses it, so
the operator has a stable pseudonymous identity without ever touching a wallet, a chain,
or a command line themselves. No dependencies, no `nak`.

  python3 keys.py ensure [path]   # print the hex secret, minting + storing it if absent
  python3 keys.py pub    <hex>    # print the x-only public key for a secret
"""
import os
import secrets
import stat
import sys

import nostr_event as ne

_N = ne._N
DEFAULT_PATH = os.path.expanduser("~/.config/vibrant/nostr.key")


def gen():
    """A uniformly random valid secret key, as 64 hex chars."""
    return "%064x" % (secrets.randbelow(_N - 1) + 1)


def ensure(path=DEFAULT_PATH):
    """Return the secret at `path`, minting and storing it 0600 if the file is absent."""
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    sk = gen()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(sk + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return sk


def pub(sk_hex):
    return ne.pubkey_from_seckey(bytes.fromhex(sk_hex)).hex()


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == "ensure":
        print(ensure(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PATH))
    elif sys.argv[1] == "gen":
        print(gen())
    elif sys.argv[1] == "pub":
        print(pub(sys.argv[2]))
    else:
        sys.exit("unknown command: " + sys.argv[1])


if __name__ == "__main__":
    main()
