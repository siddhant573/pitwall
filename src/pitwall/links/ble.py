"""Bluetooth LE link to the badge (helper side)."""
from __future__ import annotations

import asyncio
import binascii
import logging
import os
import sys
from typing import Awaitable, Callable

from .. import protocol, seal
from ..pairing import PairingStore, host_id

log = logging.getLogger(__name__)

SERVICE = "6f1c0001-9b2a-4c55-8f3e-70697477616c"
RX = "6f1c0002-9b2a-4c55-8f3e-70697477616c"   # helper -> device (write)
TX = "6f1c0003-9b2a-4c55-8f3e-70697477616c"   # device -> helper (notify)
NAME_PREFIX = "pitwall-"


class BleLink:
    """One BLE connection. Joins the hub only after the badge accepts our auth."""

    transport = "ble"

    def __init__(self, client, key: bytes | None, host: str, hub=None):
        self.client, self.key, self.host, self.hub = client, key, host, hub
        self.uid: str | None = None
        self.nonce: bytes | None = None
        self.sealer: seal.Sealer | None = None
        self.opener: seal.Opener | None = None
        self._raw = protocol.LineDecoder()
        self._hello: dict | None = None
        self._events: asyncio.Queue[dict] = asyncio.Queue()
        self._attached = False
        self._lock = asyncio.Lock()

    # -- io ------------------------------------------------------------------
    def _chunk(self) -> int:
        return max(20, int(getattr(self.client, "mtu_size", 23) or 23) - 3)

    async def _write_raw(self, data: bytes) -> None:
        for c in protocol.split_chunks(data, self._chunk()):
            await self.client.write_gatt_char(RX, c, response=True)

    async def send(self, data: bytes) -> None:
        if self.sealer is None:
            return  # never send board data before auth
        async with self._lock:  # one line at a time, in counter order
            for line in data.split(b"\n"):
                if line:
                    await self._write_raw(protocol.encode(self.sealer.seal(line)))

    async def close(self) -> None:
        try:
            await self.client.disconnect()
        except Exception:
            pass

    def on_notify(self, _sender, data: bytearray) -> None:
        for m in self._raw.feed(bytes(data)):
            if m.get("type") == "sealed":
                if self.opener is None:
                    continue
                line = self.opener.open(m)
                if line is None:
                    continue
                for inner in protocol.LineDecoder().feed(line + b"\n"):
                    if self.hub is not None and self._attached:
                        self.hub.on_message(self, inner)
                continue
            if m.get("type") == "hello":
                self._hello = m
                self.uid = m.get("uid") if isinstance(m.get("uid"), str) else None
            elif m.get("type") == "challenge":
                try:
                    self.nonce = binascii.unhexlify(m.get("nonce", ""))
                except (ValueError, binascii.Error):
                    self.nonce = None
            self._events.put_nowait(m)

    async def _wait(self, *types: str, timeout: float) -> dict | None:
        async def loop():
            while True:
                m = await self._events.get()
                if m.get("type") in types:
                    return m
        try:
            return await asyncio.wait_for(loop(), timeout)
        except asyncio.TimeoutError:
            return None

    async def open(self, timeout: float) -> bool:
        """Connect, say hello, and wait for the badge's hello + challenge."""
        await self.client.connect()
        await self.client.start_notify(TX, self.on_notify)
        await self._write_raw(protocol.encode(protocol.hello_helper()))
        got = await self._wait("challenge", timeout=timeout)
        return got is not None and self.nonce is not None and self.uid is not None

    async def start(self, timeout: float = 10.0) -> bool:
        """Connect, authenticate both ways with the stored key, then join the hub."""
        if not await self.open(timeout) or not self.key:
            await self.close()
            return False
        dn, hn = self.nonce, os.urandom(16)
        await self._write_raw(protocol.encode(
            {"type": "auth", "host": self.host, "hn": hn.hex(), "mac": seal.auth_mac(self.key, dn, hn)}))
        reply = await self._wait("auth_ok", "auth_fail", timeout=timeout)
        if not reply or reply["type"] != "auth_ok" or not seal.check_dev_mac(self.key, dn, hn, reply.get("mac", "")):
            await self.close()
            return False
        skey = seal.session_key(self.key, dn, hn)
        self.sealer = seal.Sealer(skey, dn + hn, "h2d")
        self.opener = seal.Opener(skey, dn + hn, "d2h")
        if self.hub is not None:
            self.hub.attach(self)
            self._attached = True
            self.hub.on_message(self, self._hello)
        return True


def _uid_for(name: str | None, store: PairingStore) -> str | None:
    if not name or not name.startswith(NAME_PREFIX):
        return None
    prefix = name[len(NAME_PREFIX):]
    for uid in store.all():
        if uid.startswith(prefix):
            return uid
    return None


async def _discover_default(**kw):
    from bleak import BleakScanner
    return await BleakScanner.discover(timeout=3.0, service_uuids=[SERVICE])


def _client_default(device, **kw):
    from bleak import BleakClient
    return BleakClient(device, **kw)


async def ble_watcher(hub, store: PairingStore | None = None, host: str | None = None,
                      discover: Callable[..., Awaitable[list]] = _discover_default,
                      client_factory: Callable = _client_default, interval_s: float = 5.0) -> None:
    store = store or PairingStore()
    host = host or host_id()
    live: dict[str, BleLink] = {}
    last_error: str | None = None
    while True:
        try:
            # USB came back: drop BLE to save the badge's battery
            for uid, link in list(live.items()):
                if hub.has_transport(uid, "usb"):
                    log.info("badge %s is on USB again, closing Bluetooth", uid[:8])
                    await link.close()
                    hub.on_closed(link)
                    live.pop(uid)
                elif not getattr(link.client, "is_connected", True):
                    hub.on_closed(link)
                    live.pop(uid)
            if store.all():
                found = await discover()
                if last_error is not None:
                    log.info("bluetooth scanning works again")
                    last_error = None
                for dev in found:
                    uid = _uid_for(getattr(dev, "name", None), store)
                    if uid is None or uid in live or hub.has_transport(uid, "usb"):
                        continue
                    entry = store.get(uid) or {}
                    link = BleLink(None, bytes.fromhex(entry.get("key", "")), host, hub)

                    def gone(_client, link=link):
                        hub.on_closed(link)

                    link.client = client_factory(dev, disconnected_callback=gone)
                    try:
                        ok = await link.start(timeout=10)
                    except Exception as e:
                        log.info("bluetooth connect to %s failed: %s", uid[:8], e)
                        ok = False
                    if ok:
                        log.info("badge %s connected over Bluetooth", uid[:8])
                        live[uid] = link
        except asyncio.CancelledError:
            raise
        except Exception as e:  # bluetooth off, permission denied, ...
            if str(e) != last_error:  # log once, not every 5 s
                log.info("bluetooth scan failed: %s (allow Bluetooth for pitwall in System Settings → "
                         "Privacy & Security → Bluetooth)", e)
                last_error = str(e)
        await asyncio.sleep(interval_s)
