# pitwall BLE authentication and line sealing.
# Pairing happens over USB: the helper sends a random 32-byte key on the wire.
#
# This file runs unchanged on CPython (the helper) and MicroPython (the badge),
# so it sticks to hashlib, binascii and plain bytes.
# See docs/protocol.md, "Pairing and authentication".
import binascii
import hashlib
import os

_BLOCK = 64


def hmac_sha256(key, msg):
    if len(key) > _BLOCK:
        key = hashlib.sha256(key).digest()
    key = key + b"\x00" * (_BLOCK - len(key))
    inner = hashlib.sha256(bytes(b ^ 0x36 for b in key) + msg).digest()
    return hashlib.sha256(bytes(b ^ 0x5C for b in key) + inner).digest()


def _hex(b):
    return binascii.hexlify(b).decode()


def _eq(a, b):
    if len(a) != len(b):
        return False
    r = 0
    for x, y in zip(a, b):
        r |= x ^ y
    return r == 0


def new_key():
    return os.urandom(32)


def session_key(key, dn, hn):
    return hmac_sha256(key, b"sess" + dn + hn)


def auth_mac(key, dn, hn):
    """Helper proves it knows the key (sent in `auth`)."""
    return _hex(hmac_sha256(key, b"auth" + dn + hn))


def dev_mac(key, dn, hn):
    """Device proves it knows the key (sent in `auth_ok`)."""
    return _hex(hmac_sha256(key, b"dev" + hn + dn))


def check_dev_mac(key, dn, hn, mac):
    try:
        got = binascii.unhexlify(mac)
    except Exception:
        return False
    return _eq(got, hmac_sha256(key, b"dev" + hn + dn))


def _keystream(key, d, nonce, n, length):
    out = b""
    i = 0
    prefix = key + d + nonce + n.to_bytes(8, "big")
    while len(out) < length:
        out += hashlib.sha256(prefix + i.to_bytes(4, "big")).digest()
        i += 1
    return out[:length]


class Sealer:
    def __init__(self, key, nonce, direction):
        self.key, self.nonce, self.dir, self.n = key, nonce, direction.encode(), 0

    def seal(self, line):
        n = self.n
        self.n += 1
        ks = _keystream(self.key, self.dir, self.nonce, n, len(line))
        ct = bytes(a ^ b for a, b in zip(line, ks))
        tag = hmac_sha256(self.key, self.dir + n.to_bytes(8, "big") + ct)[:16]
        return {"type": "sealed", "n": n,
                "d": binascii.b2a_base64(ct).decode().strip(), "t": _hex(tag)}


class Opener:
    def __init__(self, key, nonce, direction):
        self.key, self.nonce, self.dir, self.last = key, nonce, direction.encode(), -1

    def open(self, msg):
        try:
            n = msg["n"]
            if not isinstance(n, int) or n <= self.last:
                return None
            ct = binascii.a2b_base64(msg["d"])
            tag = binascii.unhexlify(msg["t"])
        except Exception:
            return None
        want = hmac_sha256(self.key, self.dir + n.to_bytes(8, "big") + ct)[:16]
        if not _eq(tag, want):
            return None
        self.last = n
        ks = _keystream(self.key, self.dir, self.nonce, n, len(ct))
        return bytes(a ^ b for a, b in zip(ct, ks))


class DeviceAuth:
    """Device side of auth. `keys` maps host id -> key bytes (persisted by the caller)."""

    def __init__(self, keys, rand):
        self.keys, self.rand = keys, rand
        self.nonce = None

    def challenge(self):
        self.nonce = self.rand(16)
        return {"type": "challenge", "nonce": _hex(self.nonce)}

    def handle(self, msg):
        """Returns (reply, authenticated host or None, session key or None)."""
        dn, self.nonce = self.nonce, None  # every challenge is answered at most once
        fail = ({"type": "auth_fail"}, None, None)
        host, mac, hn = msg.get("host"), msg.get("mac"), msg.get("hn")
        if msg.get("type") != "auth" or dn is None or not isinstance(host, str):
            return fail
        key = self.keys.get(host)
        try:
            got = binascii.unhexlify(mac)
            hn = binascii.unhexlify(hn)
        except Exception:
            return fail
        if key is None or len(hn) != 16 or not _eq(got, hmac_sha256(key, b"auth" + dn + hn)):
            return fail
        return {"type": "auth_ok", "mac": dev_mac(key, dn, hn)}, host, session_key(key, dn, hn)
