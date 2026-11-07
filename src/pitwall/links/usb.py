"""USB serial link to the badge."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

import serial
import serial.tools.list_ports

from .. import protocol, seal
from ..pairing import PairingStore, host_id

log = logging.getLogger(__name__)

PRODUCT_MATCH = "Badger 2350"  # verified product string: "GitHub Badger 2350 MicroPython"
BAUD = 115200


def find_badge_ports(list_ports: Callable = serial.tools.list_ports.comports) -> list[str]:
    return [p.device for p in list_ports() if PRODUCT_MATCH in (p.product or "")]


class UsbLink:
    transport = "usb"

    def __init__(self, port: str, ser) -> None:
        self.port, self.ser = port, ser
        self._lock = asyncio.Lock()

    async def send(self, data: bytes) -> None:
        async with self._lock:
            await asyncio.to_thread(self.ser.write, data)

    async def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass


async def _pair(link: UsbLink, uid: str, store: PairingStore, host: str) -> None:
    """Give the badge this Mac's key for Bluetooth. USB is a local cable, so the key can go in the clear."""
    entry = store.get(uid) or {}
    key = entry.get("key")
    if not key or len(bytes.fromhex(key)) != 32:
        key = seal.new_key().hex()
        store.add(uid, {"key": key})
    await link.send(protocol.encode({"type": "pair_key", "host": host, "key": key}))


async def _pump(hub, link: UsbLink, store: PairingStore | None, host: str | None) -> None:
    dec = protocol.LineDecoder()
    try:
        await link.send(protocol.encode(protocol.hello_helper()))
        while True:
            data = await asyncio.to_thread(link.ser.read, max(1, getattr(link.ser, "in_waiting", 0) or 1))
            if data:
                for msg in dec.feed(data):
                    hub.on_message(link, msg)
                    uid = msg.get("uid")
                    if msg.get("type") == "hello" and store is not None and isinstance(uid, str) and uid:
                        await _pair(link, uid, store, host)
    except (serial.SerialException, OSError) as e:
        log.info("badge on %s disconnected: %s", link.port, e)
    finally:
        hub.on_closed(link)
        await link.close()


async def usb_watcher(hub, interval_s: float = 2.0,
                      list_ports: Callable = serial.tools.list_ports.comports,
                      serial_factory: Callable = serial.Serial,
                      store: PairingStore | None = None, host: str | None = None) -> None:
    if store is None and host is None:
        store, host = PairingStore(), host_id()
    live: dict[str, asyncio.Task] = {}
    warned: set[str] = set()
    try:
        while True:
            for port in find_badge_ports(list_ports):
                if port in live and not live[port].done():
                    continue
                try:
                    ser = serial_factory(port, baudrate=BAUD, timeout=0.2)
                except (serial.SerialException, OSError) as e:
                    if port not in warned:
                        log.warning("badge port %s is in use or unavailable (%s); will keep retrying", port, e)
                        warned.add(port)
                    continue
                warned.discard(port)
                link = UsbLink(port, ser)
                hub.attach(link)
                log.info("badge connected over USB on %s", port)
                live[port] = asyncio.create_task(_pump(hub, link, store, host))
            await asyncio.sleep(interval_s)
    finally:
        for t in live.values():
            t.cancel()
