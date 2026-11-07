"""The device hub: which links are connected, which one speaks for each device."""
from __future__ import annotations

import asyncio
import itertools
import logging
from typing import Callable, Protocol

from . import protocol, terminals
from .board import Board

log = logging.getLogger(__name__)

_PRIORITY = {"usb": 0, "ble": 1, "socket": 2}


class Link(Protocol):
    transport: str  # "socket" | "usb" | "ble"

    async def send(self, data: bytes) -> None: ...

    async def close(self) -> None: ...


class _State:
    _order = itertools.count()

    def __init__(self) -> None:
        self.uid: str | None = None
        self.seq = next(self._order)


class Hub:
    def __init__(self, board: Board, focus: Callable[[dict | None], str] = terminals.focus):
        self.board = board
        self._focus = focus
        self._links: dict[Link, _State] = {}
        self._tasks: set[asyncio.Task] = set()

    # -- links ---------------------------------------------------------------
    def attach(self, link: Link) -> None:
        self._links[link] = _State()

    def on_closed(self, link: Link) -> None:
        st = self._links.pop(link, None)
        if st is None or st.uid is None:
            return
        successor = self._active_for(st.uid)
        if successor is not None:
            self._send(successor, self.board.snapshot())

    def has_transport(self, uid: str, transport: str) -> bool:
        return any(st.uid == uid and link.transport == transport for link, st in self._links.items())

    def active_links(self) -> list[Link]:
        uids = {st.uid for st in self._links.values() if st.uid is not None}
        return [link for uid in uids if (link := self._active_for(uid)) is not None]

    def _active_for(self, uid: str) -> Link | None:
        cands = [(_PRIORITY.get(link.transport, 9), st.seq, link)
                 for link, st in self._links.items() if st.uid == uid]
        return min(cands, key=lambda c: (c[0], c[1]))[2] if cands else None

    def _is_active(self, link: Link) -> bool:
        st = self._links.get(link)
        return st is not None and st.uid is not None and self._active_for(st.uid) is link

    # -- messages ------------------------------------------------------------
    def on_message(self, link: Link, msg: dict) -> None:
        st = self._links.get(link)
        if st is None:
            return
        kind = msg.get("type")
        if kind == "hello":
            uid = msg.get("uid")
            st.uid = uid if isinstance(uid, str) and uid else f"anon-{st.seq}"
            if self._is_active(link):
                self._send(link, protocol.hello_helper())
                self._send(link, self.board.snapshot())
            return
        if not self._is_active(link):
            return
        if kind == "focus":
            s = self.board.get(msg.get("id")) if isinstance(msg.get("id"), str) else None
            if s is not None and s.terminal:
                self._spawn(self._focus_one(s.id))
        elif kind == "focus_next_waiting":
            self._spawn(self._focus_next_waiting())

    def apply_session(self, event: dict) -> None:
        sid = event.get("id")
        before = self.board.get(sid) if isinstance(sid, str) else None
        was_box = before is not None and before.state == "box"
        if not self.board.apply(event):
            return
        snap = self.board.snapshot()
        entered_box = event.get("state") == "box" and not was_box
        for link in self.active_links():
            self._send(link, snap)
            if entered_box:
                self._send(link, protocol.alert(sid))

    async def broadcast(self) -> None:
        data = protocol.encode(self.board.snapshot())
        await asyncio.gather(*(self._safe_send(link, data) for link in self.active_links()))

    # -- plumbing ------------------------------------------------------------
    def _send(self, link: Link, msg: dict) -> None:
        self._spawn(self._safe_send(link, protocol.encode(msg)))

    async def _safe_send(self, link: Link, data: bytes) -> None:
        try:
            await link.send(data)
        except Exception as e:  # a broken link must not take the hub down
            log.info("send failed on %s link: %s", link.transport, e)

    async def _focus_one(self, sid: str) -> str:
        s = self.board.get(sid)
        if s is None or not s.terminal:
            return "error"
        try:
            result = await asyncio.to_thread(self._focus, s.terminal)
        except Exception as e:
            log.info("focus failed: %s", e)
            return "error"
        log.debug("focus %s → %s", s.terminal, result)
        if result == "error":
            log.info("couldn't switch to %s's tab: allow pitwall to control iTerm2 in System Settings → "
                     "Privacy & Security → Automation (and check iTerm2 is running)", s.id[:8])
        if result == "missing":  # the tab was closed without SessionEnd: drop the ghost
            self.apply_session({"type": "session", "id": sid, "state": "end"})
        return result

    async def _focus_next_waiting(self) -> None:
        for _ in range(50):
            s = self.board.next_waiting()
            if s is None or await self._focus_one(s.id) != "missing":
                return

    def _spawn(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
