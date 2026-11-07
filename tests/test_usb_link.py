import asyncio
from types import SimpleNamespace

import serial

from fakes import settle
from pitwall.links.usb import UsbLink, find_badge_ports, usb_watcher
from pitwall.protocol import encode, hello_device


def ports(*items):
    return lambda: [SimpleNamespace(device=d, product=p) for d, p in items]


BADGER = ("/dev/cu.usbmodem3101", "GitHub Badger 2350 MicroPython")


def test_find_badge_ports_only_badger():
    lp = ports(BADGER, ("/dev/cu.Bluetooth-Incoming-Port", None), ("/dev/cu.usbserial-1", "FT232R"))
    assert find_badge_ports(lp) == ["/dev/cu.usbmodem3101"]


class FakeSerial:
    def __init__(self, chunks=(), fail_after=False):
        self.chunks = list(chunks)
        self.fail_after = fail_after
        self.written = b""
        self.closed = False
        self.in_waiting = 0

    def read(self, n=1):
        if self.chunks:
            return self.chunks.pop(0)
        if self.fail_after:
            raise serial.SerialException("device disconnected")
        import time
        time.sleep(0.01)
        return b""

    def write(self, data):
        self.written += data
        return len(data)

    def close(self):
        self.closed = True


class RecHub:
    def __init__(self):
        self.attached, self.msgs, self.closed = [], [], []

    def attach(self, link):
        self.attached.append(link)

    def on_message(self, link, msg):
        self.msgs.append(msg)

    def on_closed(self, link):
        self.closed.append(link)


async def wait_for(pred, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        if pred():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("timed out")


async def test_reads_messages_and_closes_once_on_error():
    hello = encode(hello_device("badger2350", "B1", "usb", {}))
    fake = FakeSerial([b"garbage\n", hello[:10], hello[10:]], fail_after=True)
    hub = RecHub()
    task = asyncio.create_task(usb_watcher(hub, interval_s=0.05, list_ports=ports(BADGER),
                                           serial_factory=lambda port, **kw: fake))
    await wait_for(lambda: hub.closed)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert [m["type"] for m in hub.msgs][:1] == ["hello"]
    assert len(hub.closed) == 1 and fake.closed
    assert b'"device":"helper"' in fake.written  # helper says hello on open


async def test_port_reappearing_reattaches():
    opened = []

    def factory(port, **kw):
        s = FakeSerial(fail_after=len(opened) == 0)
        opened.append(s)
        return s

    hub = RecHub()
    task = asyncio.create_task(usb_watcher(hub, interval_s=0.05, list_ports=ports(BADGER),
                                           serial_factory=factory))
    await wait_for(lambda: len(hub.attached) >= 2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert len(opened) >= 2


async def test_busy_port_is_retried(caplog):
    calls = []

    def factory(port, **kw):
        calls.append(port)
        if len(calls) < 3:
            raise serial.SerialException("[Errno 16] Resource busy")
        return FakeSerial()

    hub = RecHub()
    task = asyncio.create_task(usb_watcher(hub, interval_s=0.02, list_ports=ports(BADGER),
                                           serial_factory=factory))
    await wait_for(lambda: hub.attached)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert len(calls) >= 3
    assert sum("busy" in r.message.lower() or "in use" in r.message.lower() for r in caplog.records) <= 1


async def test_send_writes_bytes():
    fake = FakeSerial()
    link = UsbLink("/dev/x", fake)
    await link.send(b"abc\n")
    assert fake.written == b"abc\n" and link.transport == "usb"


async def test_usb_hello_pairs_badge_with_random_key(tmp_path):
    from pitwall.pairing import PairingStore
    store = PairingStore(tmp_path / "pairing.json")
    hello = encode(hello_device("badger2350", "B1", "usb", {}))
    fake = FakeSerial([hello], fail_after=False)
    hub = RecHub()
    task = asyncio.create_task(usb_watcher(hub, interval_s=0.05, list_ports=ports(BADGER),
                                           serial_factory=lambda port, **kw: fake,
                                           store=store, host="HOST1"))
    await wait_for(lambda: b"pair_key" in fake.written)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    from pitwall.protocol import LineDecoder
    sent = [m for m in LineDecoder().feed(fake.written) if m["type"] == "pair_key"]
    assert sent[0]["host"] == "HOST1" and len(bytes.fromhex(sent[0]["key"])) == 32
    assert store.get("B1")["key"] == sent[0]["key"]
    # a second hello re-sends the same key (self-healing if the badge lost it)
    fake2 = FakeSerial([hello])
    task = asyncio.create_task(usb_watcher(hub, interval_s=0.05, list_ports=ports(BADGER),
                                           serial_factory=lambda port, **kw: fake2,
                                           store=store, host="HOST1"))
    await wait_for(lambda: b"pair_key" in fake2.written)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert [m for m in LineDecoder().feed(fake2.written) if m["type"] == "pair_key"][0]["key"] == sent[0]["key"]
