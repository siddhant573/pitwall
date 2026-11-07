import asyncio
import os
from types import SimpleNamespace

from fakes import FakeLink, settle
from pitwall import seal
from pitwall.board import Board
from pitwall.hub import Hub
from pitwall.links.ble import RX, TX, BleLink, ble_watcher
from pitwall.pairing import PairingStore
from fakes import session_event
from pitwall.protocol import LineDecoder, encode, hello_device

UID = "0123abcd4567ef89"


class FakeBadge:
    """Device side, built on the same seal.py the badge runs."""

    def __init__(self, keys=None, forge_ok=False, replay=None):
        self.auth = seal.DeviceAuth(keys if keys is not None else {}, rand=os.urandom)
        self.dec = LineDecoder()
        self.notify = None
        self.received = []
        self.sealer = self.opener = None
        self.forge_ok = forge_ok          # answer auth_ok without knowing the key
        self.replay = replay              # (old challenge nonce hex, [old sealed d2h lines])

    def emit(self, msg):
        data = encode(msg)
        for i in range(0, len(data), 20):
            self.notify(None, bytearray(data[i:i + 20]))

    def on_write(self, data):
        for m in self.dec.feed(data):
            t = m["type"]
            if t == "hello":
                self.emit(hello_device("badger2350", UID, "ble", {}))
                if self.replay:
                    self.emit({"type": "challenge", "nonce": self.replay[0]})
                else:
                    self.emit(self.auth.challenge())
            elif t == "auth":
                if self.forge_ok:
                    self.emit({"type": "auth_ok", "mac": "00" * 32})
                    for line in (self.replay[1] if self.replay else []):
                        self.emit(line)
                    continue
                dn = self.auth.nonce
                reply, host, skey = self.auth.handle(m)
                self.emit(reply)
                if host:
                    hn = bytes.fromhex(m["hn"])
                    self.sealer = seal.Sealer(skey, dn + hn, "d2h")
                    self.opener = seal.Opener(skey, dn + hn, "h2d")
            elif t == "sealed" and self.opener:
                line = self.opener.open(m)
                if line is not None:
                    self.received += LineDecoder().feed(line + b"\n")

    def press(self, msg):
        self.emit(self.sealer.seal(encode(msg).rstrip(b"\n")))


class FakeClient:
    def __init__(self, badge, mtu=64, yield_on_write=False):
        self.badge, self.mtu_size, self.writes = badge, mtu, []
        self.yield_on_write = yield_on_write
        self.is_connected = False

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False

    async def start_notify(self, uuid, cb):
        assert uuid == TX
        self.badge.notify = cb

    async def write_gatt_char(self, uuid, data, response=True):
        assert uuid == RX and response
        if self.yield_on_write:
            await asyncio.sleep(0)
        self.writes.append(bytes(data))
        self.badge.on_write(bytes(data))


def mkhub(calls=None):
    return Hub(Board(clock=lambda: 0.0), focus=lambda t: (calls.append(t) if calls is not None else None) or "ok")


async def test_auth_then_sealed_chunked_traffic():
    key = seal.new_key()
    badge = FakeBadge(keys={"HOST1": key})
    client = FakeClient(badge, mtu=40)
    hub = mkhub()
    link = BleLink(client, key, "HOST1", hub)
    assert await link.start(timeout=2)
    await settle()
    assert hub.active_links() == [link]
    hub.apply_session(session_event("claude-code", "s1", "box", "café-🏎️", "/w/café-🏎️",
                                    {"kind": "iterm2", "ref": "U"}))
    await settle(30)
    assert all(len(w) <= 37 for w in client.writes)
    assert any(m["type"] == "board" and m["sessions"] and m["sessions"][0]["label"] == "café-🏎️"
               for m in badge.received)
    assert not any(b"caf" in w for w in client.writes)


async def test_board_and_alert_both_arrive_when_writes_yield():
    key = seal.new_key()
    badge = FakeBadge(keys={"HOST1": key})
    client = FakeClient(badge, mtu=23, yield_on_write=True)
    hub = mkhub()
    link = BleLink(client, key, "HOST1", hub)
    assert await link.start(timeout=2)
    await settle(20)
    badge.received.clear()
    hub.apply_session(session_event("claude-code", "s1", "box", "api", "/w/api", {"kind": "iterm2", "ref": "U"}))
    for _ in range(400):
        await asyncio.sleep(0)
    assert [m["type"] for m in badge.received] == ["board", "alert"]


async def test_wrong_key_never_reaches_hub():
    badge = FakeBadge(keys={"HOST1": seal.new_key()})
    hub = mkhub()
    link = BleLink(FakeClient(badge), seal.new_key(), "HOST1", hub)
    assert await link.start(timeout=0.5) is False
    assert hub.active_links() == []


async def test_fake_badge_replaying_old_session_is_rejected():
    key = seal.new_key()
    calls = []
    # record a genuine session: its challenge and a sealed button press
    real = FakeBadge(keys={"HOST1": key})
    hub0 = mkhub(calls)
    hub0.apply_session(session_event("claude-code", "s1", "box", "api", "/w/api", {"kind": "iterm2", "ref": "U"}))
    seen = []
    client0 = FakeClient(real)
    link0 = BleLink(client0, key, "HOST1", hub0)
    orig = link0.on_notify
    link0.on_notify = lambda s, d: (seen.append(bytes(d)), orig(s, d))
    assert await link0.start(timeout=2)
    real.press({"type": "focus_next_waiting"})
    await settle(20)
    assert len(calls) == 1
    msgs = LineDecoder().feed(b"".join(seen))
    old_nonce = next(m["nonce"] for m in msgs if m["type"] == "challenge")
    old_sealed = [m for m in msgs if m["type"] == "sealed"]

    # an attacker replays that challenge, forges auth_ok, and replays the press
    fake = FakeBadge(forge_ok=True, replay=(old_nonce, old_sealed))
    hub1 = mkhub(calls)
    hub1.apply_session(session_event("claude-code", "s1", "box", "api", "/w/api", {"kind": "iterm2", "ref": "U"}))
    link1 = BleLink(FakeClient(fake), key, "HOST1", hub1)
    assert await link1.start(timeout=0.5) is False
    await settle(20)
    assert hub1.active_links() == [] and len(calls) == 1


async def test_device_button_reaches_hub_after_auth():
    key = seal.new_key()
    badge = FakeBadge(keys={"HOST1": key})
    calls = []
    hub = mkhub(calls)
    hub.apply_session(session_event("claude-code", "s1", "box", "api", "/w/api", {"kind": "iterm2", "ref": "U"}))
    link = BleLink(FakeClient(badge), key, "HOST1", hub)
    assert await link.start(timeout=2)
    badge.press({"type": "focus_next_waiting"})
    await settle(20)
    assert calls == [{"kind": "iterm2", "ref": "U"}]


async def test_watcher_ignores_unpaired_and_skips_uid_on_usb(tmp_path):
    store = PairingStore(tmp_path / "pairing.json")
    store.add(UID, {"key": "00" * 32})
    hub = mkhub()
    usb = FakeLink("usb")
    hub.attach(usb)
    hub.on_message(usb, hello_device("badger2350", UID, "usb", {}) | {"v": 1})
    connects = []

    async def discover(**kw):
        return [SimpleNamespace(name="pitwall-0123abcd", address="A1"),
                SimpleNamespace(name="pitwall-deadbeef", address="A2")]

    def factory(device, **kw):
        connects.append(device.address)
        return FakeClient(FakeBadge())

    task = asyncio.create_task(ble_watcher(hub, store, host="HOST1", discover=discover,
                                           client_factory=factory, interval_s=0.01))
    await asyncio.sleep(0.1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert connects == []
    assert hub.has_transport(UID, "usb")


async def test_scan_failures_are_logged_once(tmp_path, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="pitwall.links.ble")
    store = PairingStore(tmp_path / "pairing.json")
    store.add(UID, {"key": "00" * 32})

    async def discover(**kw):
        raise RuntimeError("Bluetooth is off")

    task = asyncio.create_task(ble_watcher(mkhub(), store, host="H", discover=discover, interval_s=0.01))
    await asyncio.sleep(0.15)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert sum("Bluetooth is off" in r.message for r in caplog.records) == 1
