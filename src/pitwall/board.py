"""The session board: every known agent session and its state."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable

from . import protocol

_ORDER = {"box": 0, "red": 1, "done": 2, "green": 3}


@dataclass
class Session:
    id: str
    cwd: str
    state: str
    since: float
    last_seen: float
    terminal: dict | None
    seq: int = 0  # first-seen order, for stable label suffixes
    title: str | None = None  # the terminal tab's title, when known
    name: str = ""  # agent-provided label, used when there's no folder


class Board:
    def __init__(self, clock: Callable[[], float] = time.monotonic, ttl_s: float = 6 * 3600):
        self._clock = clock
        self._ttl = ttl_s
        self._sessions: dict[str, Session] = {}
        self._seq = 0

    # -- mutation --------------------------------------------------------
    def apply(self, event: dict) -> bool:
        """Apply a `session` event. Returns True if the visible board changed."""
        sid = event.get("id")
        state = event.get("state")
        if not isinstance(sid, str) or not sid:
            return False
        now = self._clock()
        if state == "end":
            return self._sessions.pop(sid, None) is not None
        if state not in _ORDER:
            return False
        cwd = event.get("cwd") or ""
        terminal = event.get("terminal") or None
        s = self._sessions.get(sid)
        if s is None:
            self._seq += 1
            label = event.get("label") if isinstance(event.get("label"), str) else ""
            self._sessions[sid] = Session(sid, cwd, state, now, now, terminal, self._seq, name=label)
            return True
        s.last_seen = now
        changed = False
        if s.state != state:
            s.state, s.since, changed = state, now, True
        if terminal and terminal != s.terminal:
            s.terminal, changed = terminal, True
        if cwd and cwd != s.cwd:
            s.cwd, changed = cwd, True
        return changed

    def set_titles(self, by_ref: dict) -> bool:
        """Apply terminal tab titles (ref -> title). An empty mapping means unknown: keep the last ones."""
        if not by_ref:
            return False
        changed = False
        for s in self._sessions.values():
            ref = (s.terminal or {}).get("ref")
            if ref in by_ref and by_ref[ref] != s.title:
                s.title, changed = by_ref[ref], True
        return changed

    def expire(self) -> bool:
        cutoff = self._clock() - self._ttl
        stale = [k for k, s in self._sessions.items() if s.last_seen < cutoff]
        for k in stale:
            del self._sessions[k]
        return bool(stale)

    # -- queries -----------------------------------------------------------
    def get(self, id: str) -> Session | None:
        return self._sessions.get(id)

    def next_waiting(self) -> Session | None:
        boxes = [s for s in self._sessions.values() if s.state == "box"]
        return min(boxes, key=lambda s: (s.since, s.seq)) if boxes else None

    def labels(self) -> dict[str, str]:
        groups: dict[str, list[Session]] = {}
        for s in self._sessions.values():
            groups.setdefault(os.path.basename(s.cwd.rstrip("/")) or s.name or "session", []).append(s)
        out = {}
        for base, members in groups.items():
            for i, s in enumerate(sorted(members, key=lambda s: s.seq)):
                out[s.id] = base if i == 0 else f"{base}·{i + 1}"
        return out

    def snapshot(self) -> dict:
        now = self._clock()
        labels = self.labels()
        ordered = sorted(
            self._sessions.values(),
            key=lambda s: (_ORDER[s.state], s.since if s.state == "box" else 0, labels[s.id]),
        )
        sessions = [{"id": s.id, "label": labels[s.id], "title": s.title, "state": s.state,
                     "age_s": int(now - s.since), "focusable": bool(s.terminal)}
                    for s in ordered]
        counts = {k: 0 for k in _ORDER}
        for s in ordered:
            counts[s.state] += 1
        return protocol.board(sessions, counts)
