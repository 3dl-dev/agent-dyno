#!/usr/bin/env python3
"""
relay_io: the skill's Nostr transport, Python 3 standard library only.

A minimal RFC 6455 WebSocket client, just enough to publish an event to a relay and
read the OK, or to run a REQ and collect events until EOSE. This is the skill's I/O
tool, the piece a recipe cannot do in prose; the signing core (nostr_event.py) stays
pure and opens no socket. No dependencies, no `nak`, nothing to install.

  python3 relay_io.py publish <ws-url>          # event JSON on stdin -> prints OK line
  python3 relay_io.py query   <ws-url> <json-filter>   # prints one event JSON per line
"""
import base64
import json
import os
import socket
import ssl
import struct
import sys
import time
from urllib.parse import urlparse


def _connect(url):
    u = urlparse(url)
    host = u.hostname
    port = u.port or (443 if u.scheme == "wss" else 80)
    path = u.path or "/"
    if u.query:
        path += "?" + u.query
    sock = socket.create_connection((host, port), timeout=10)
    if u.scheme == "wss":
        sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
           f"Sec-WebSocket-Version: 13\r\n\r\n")
    sock.sendall(req.encode())
    # read headers until blank line; a 101 is the only success
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("relay closed during handshake")
        buf += chunk
    if b" 101 " not in buf.split(b"\r\n", 1)[0]:
        raise ConnectionError("relay did not accept the websocket upgrade")
    leftover = buf.split(b"\r\n\r\n", 1)[1]
    return sock, bytearray(leftover)


def _send_text(sock, text):
    payload = text.encode("utf-8")
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    n = len(payload)
    header = bytearray([0x81])  # FIN + text
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", n)
    sock.sendall(bytes(header) + mask + masked)


def _frames(sock, buf, deadline):
    """Yield decoded text messages from the socket (server frames are unmasked)."""
    while True:
        while len(buf) < 2:
            sock.settimeout(max(0.1, deadline - time.monotonic()))
            chunk = sock.recv(4096)
            if not chunk:
                return
            buf += chunk
        b0, b1 = buf[0], buf[1]
        opcode = b0 & 0x0F
        ln = b1 & 0x7F
        idx = 2
        if ln == 126:
            while len(buf) < 4:
                buf += sock.recv(4096)
            ln = struct.unpack(">H", bytes(buf[2:4]))[0]
            idx = 4
        elif ln == 127:
            while len(buf) < 10:
                buf += sock.recv(4096)
            ln = struct.unpack(">Q", bytes(buf[2:10]))[0]
            idx = 10
        while len(buf) < idx + ln:
            sock.settimeout(max(0.1, deadline - time.monotonic()))
            chunk = sock.recv(4096)
            if not chunk:
                return
            buf += chunk
        payload = bytes(buf[idx:idx + ln])
        del buf[:idx + ln]
        if opcode == 0x8:  # close
            return
        if opcode in (0x1, 0x2):
            yield payload.decode("utf-8", "replace")


def publish(url, event, timeout=10):
    """Send ["EVENT", event]; return (ok: bool, message: str) from the relay's OK."""
    sock, buf = _connect(url)
    try:
        _send_text(sock, json.dumps(["EVENT", event]))
        deadline = time.monotonic() + timeout
        for msg in _frames(sock, buf, deadline):
            try:
                d = json.loads(msg)
            except ValueError:
                continue
            if isinstance(d, list) and d and d[0] == "OK" and d[1] == event.get("id"):
                return bool(d[2]), (d[3] if len(d) > 3 else "")
            if time.monotonic() > deadline:
                break
        return False, "no OK received before timeout"
    finally:
        sock.close()


def query(url, filters, timeout=10):
    """Send a REQ with the given filter objects; collect EVENTs until EOSE. Returns a list."""
    sock, buf = _connect(url)
    events = []
    try:
        _send_text(sock, json.dumps(["REQ", "s"] + filters))
        deadline = time.monotonic() + timeout
        for msg in _frames(sock, buf, deadline):
            try:
                d = json.loads(msg)
            except ValueError:
                continue
            if isinstance(d, list) and d and d[0] == "EVENT" and d[1] == "s":
                events.append(d[2])
            elif isinstance(d, list) and d and d[0] == "EOSE" and d[1] == "s":
                break
            if time.monotonic() > deadline:
                break
        return events
    finally:
        sock.close()


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, url = sys.argv[1], sys.argv[2]
    if cmd == "publish":
        event = json.load(sys.stdin)
        ok, msg = publish(url, event)
        print(json.dumps({"ok": ok, "message": msg, "id": event.get("id")}))
        sys.exit(0 if ok else 1)
    if cmd == "query":
        filt = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        for ev in query(url, [filt]):
            sys.stdout.write(json.dumps(ev) + "\n")
        sys.exit(0)
    sys.exit("unknown command: " + cmd)


if __name__ == "__main__":
    main()
