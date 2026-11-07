"""`pitwall serve`: the helper process."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Awaitable, Callable, Iterable

from . import paths
from .board import Board
from .hub import Hub
from .protocol import LineDecoder

log = logging.getLogger(__name__)

HEARTBEAT_S = 5.0
EXPIRE_EVERY_S = 60.0

Watcher = Callable[[Hub], Awaitable[None]]


class SocketLink:
    transport = "socket"

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer

    async def send(self, data: bytes) -> None:
        self.writer.write(data)
        await self.writer.drain()

    async def close(self) -> None:
        self.writer.close()


async def title_watcher(hub: Hub, titles: Callable[[], dict] | None = None, interval_s: float = 3.0) -> None:
    """Keep each session's terminal tab title fresh (shown next to the folder name)."""
    if titles is None:
        from .terminals.iterm2 import titles
    while True:
        try:
            if hub.board.set_titles(await asyncio.to_thread(titles)):
                await hub.broadcast()
        except Exception as e:
            log.debug("title lookup failed: %s", e)
        await asyncio.sleep(interval_s)


def watchers_for(cfg) -> list[Watcher]:
    """The background jobs a config needs: one per device transport, plus terminal titles."""
    watchers: list[Watcher] = []
    if cfg.terminal == "iterm2":
        watchers.append(title_watcher)
    transports = cfg.devices.get("badger2350", [])
    if "usb" in transports:
        from .links.usb import usb_watcher
        watchers.append(usb_watcher)
    if "ble" in transports:
        from .links.ble import ble_watcher
        watchers.append(ble_watcher)
    return watchers


class AlreadyRunning(RuntimeError):
    pass


async def _bind_path(path: Path) -> None:
    """Remove a stale socket file, but never one a live helper is listening on."""
    if not (path.exists() or path.is_symlink()):
        return
    try:
        _, w = await asyncio.wait_for(asyncio.open_unix_connection(str(path)), 1.0)
    except (OSError, asyncio.TimeoutError):
        path.unlink()
        return
    w.close()
    raise AlreadyRunning(f"pitwall is already running (socket {path} is live)")


async def serve(home: Path | None = None, watchers: Iterable[Watcher] | None = None,
                board: Board | None = None, cfg=None) -> None:
    home = paths.ensure_home(home)
    hub = Hub(board or Board())
    hook_path, dev_path = paths.hook_socket(home), paths.device_socket(home)

    async def on_hook(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            data = await asyncio.wait_for(reader.read(64 * 1024), 2.0)
            for msg in LineDecoder().feed(data if data.endswith(b"\n") else data + b"\n"):
                if msg.get("type") == "session":
                    hub.apply_session(msg)
        except Exception as e:
            log.debug("bad hook connection: %s", e)
        finally:
            writer.close()

    async def on_device(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        link = SocketLink(reader, writer)
        hub.attach(link)
        dec = LineDecoder()
        try:
            while data := await reader.read(4096):
                for msg in dec.feed(data):
                    hub.on_message(link, msg)
        except (ConnectionError, OSError):
            pass
        finally:
            hub.on_closed(link)
            writer.close()

    for p in (hook_path, dev_path):
        await _bind_path(p)
    hook_srv = await asyncio.start_unix_server(on_hook, path=str(hook_path))
    dev_srv = await asyncio.start_unix_server(on_device, path=str(dev_path))
    owned = {}
    for p in (hook_path, dev_path):
        os.chmod(p, 0o600)
        owned[p] = p.stat().st_ino

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            await hub.broadcast()

    async def expire() -> None:
        while True:
            await asyncio.sleep(EXPIRE_EVERY_S)
            if hub.board.expire():
                await hub.broadcast()

    jobs = [heartbeat(), expire()]
    if watchers is None:
        from .config import load
        watchers = watchers_for(cfg or load())
    jobs += [w(hub) for w in watchers]
    log.info("pitwall helper listening in %s", home)
    try:
        async with hook_srv, dev_srv:
            await asyncio.gather(*jobs)
    finally:
        for p, ino in owned.items():  # only remove sockets this process created
            try:
                if p.stat().st_ino == ino:
                    p.unlink()
            except FileNotFoundError:
                pass
