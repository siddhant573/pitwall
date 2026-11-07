# pitwall badge: USB serial and Bluetooth LE links.
import json
import os
import select
import sys
import time

import bluetooth
import model
import seal

KEYS_FILE = "/state/pitwall_keys.json"

_SERVICE = bluetooth.UUID("6f1c0001-9b2a-4c55-8f3e-70697477616c")
_RX = (bluetooth.UUID("6f1c0002-9b2a-4c55-8f3e-70697477616c"), 0x0008 | 0x0004)  # write, write-no-response
_TX = (bluetooth.UUID("6f1c0003-9b2a-4c55-8f3e-70697477616c"), 0x0010)           # notify

_IRQ_CENTRAL_CONNECT = 1
_IRQ_CENTRAL_DISCONNECT = 2
_IRQ_GATTS_WRITE = 3
_IRQ_MTU_EXCHANGED = 21


def _line(msg):
    m = dict(msg)
    m["v"] = 1
    return json.dumps(m).encode() + b"\n"


class Usb:
    def __init__(self):
        self.poll = select.poll()
        self.poll.register(sys.stdin, select.POLLIN)
        self.dec = model.Decoder()
        self.stdin = getattr(sys.stdin, "buffer", sys.stdin)

    def read(self):
        data = b""
        while len(data) < 2048 and self.poll.poll(0):
            c = self.stdin.read(1)
            if not c:
                break
            data += c if isinstance(c, bytes) else c.encode()
        return self.dec.feed(data) if data else []

    def send(self, msg):
        try:
            sys.stdout.write(_line(msg).decode())
        except Exception:
            pass


def load_keys():
    try:
        with open(KEYS_FILE) as f:
            return {h: bytes.fromhex(k) for h, k in json.load(f).items()}
    except Exception:
        return {}


def save_keys(keys):
    try:
        with open(KEYS_FILE, "w") as f:
            json.dump({h: k.hex() for h, k in keys.items()}, f)
    except Exception as e:
        print("pitwall: could not save keys", e)


def _adv(adv_type, value):
    return bytes((len(value) + 1, adv_type)) + value


class Ble:
    def __init__(self, uid, hello):
        self.uid = uid
        self.hello = hello
        self.name = "pitwall-" + uid[:8]
        self.keys = load_keys()
        self.ble = bluetooth.BLE()
        self._start()

    def _start(self):
        self.ble.active(True)
        try:
            self.ble.config(gap_name=self.name, mtu=247)
        except Exception:
            self.ble.config(gap_name=self.name)
        self.ble.irq(self._irq)
        ((self.h_tx, self.h_rx),) = self.ble.gatts_register_services(((_SERVICE, (_TX, _RX)),))
        self.ble.gatts_set_buffer(self.h_rx, 512, True)
        self.conn = None
        self.mtu = 23
        self.inbox = b""
        self.last_adv = None
        self._reset()
        self._advertise()

    def restart(self):
        """Turn the radio off and on again, then advertise fresh. For the 'Restart Bluetooth' button."""
        try:
            if self.conn is not None:
                self.ble.gap_disconnect(self.conn)
        except Exception:
            pass
        try:
            self.ble.active(False)
        except Exception:
            pass
        time.sleep_ms(200)
        self._start()

    def _reset(self):
        self.dec = model.Decoder()
        self.auth = seal.DeviceAuth(self.keys, os.urandom)
        self.sealer = None
        self.opener = None

    def add_key(self, host, key):
        """Called when the helper sends this Mac's key over USB."""
        if self.keys.get(host) != key:
            self.keys[host] = key
            save_keys(self.keys)

    @property
    def authed(self):
        return self.sealer is not None

    def _advertise(self):
        flags = _adv(0x01, b"\x06")
        uuid = _adv(0x07, bytes(reversed(bytes.fromhex("6f1c00019b2a4c558f3e70697477616c"))))
        name = _adv(0x09, self.name.encode())
        try:
            self.ble.gap_advertise(200_000, adv_data=flags + uuid, resp_data=name)
        except Exception as e:
            print("pitwall: advertise failed", e)
        self.last_adv = time.ticks_ms()

    def keep_advertising(self):
        since = None if self.last_adv is None else time.ticks_diff(time.ticks_ms(), self.last_adv)
        if model.readvertise_due(self.conn is not None, since):
            self._advertise()

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self.conn = data[0]
            self._reset()
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self.conn = None
            self._reset()
            self._advertise()
        elif event == _IRQ_GATTS_WRITE:
            self.inbox += self.ble.gatts_read(self.h_rx)
        elif event == _IRQ_MTU_EXCHANGED:
            self.mtu = data[1]

    def _notify(self, data):
        if self.conn is None:
            return
        size = max(20, self.mtu - 3)
        for i in range(0, len(data), size):
            for _ in range(20):
                try:
                    self.ble.gatts_notify(self.conn, self.h_tx, data[i:i + size])
                    break
                except OSError:
                    time.sleep_ms(5)

    def _raw(self, msg):
        self._notify(_line(msg))

    def send(self, msg):
        if self.sealer is not None:
            self._notify(_line(self.sealer.seal(_line(msg).rstrip(b"\n"))))

    def read(self):
        """Returns app messages (only after auth). Handles the handshake itself."""
        if not self.inbox:
            return []
        data, self.inbox = self.inbox, b""
        out = []
        for m in self.dec.feed(data):
            kind = m.get("type")
            if kind == "sealed":
                if self.opener is not None:
                    line = self.opener.open(m)
                    if line is not None:
                        out += model.Decoder().feed(line + b"\n")
            elif kind == "hello" and not self.authed:
                self._raw(self.hello)
                self._raw(self.auth.challenge())
            elif kind == "auth" and not self.authed:
                dn = self.auth.nonce
                reply, host, skey = self.auth.handle(m)
                self._raw(reply)
                if host:
                    hn = bytes.fromhex(m["hn"])
                    self.sealer = seal.Sealer(skey, dn + hn, "d2h")
                    self.opener = seal.Opener(skey, dn + hn, "h2d")
        return out
