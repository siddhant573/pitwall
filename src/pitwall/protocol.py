"""pitwall protocol v1: JSON objects, one per line, UTF-8, each with "v": 1.

See docs/protocol.md for the full contract.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

VERSION = 1
MAX_LINE = 64 * 1024  # drop runaway lines without a newline


def encode(msg: dict) -> bytes:
    out = dict(msg)
    out["v"] = VERSION
    return json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


class LineDecoder:
    """Turns a byte stream into protocol messages, skipping anything invalid."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, data: bytes) -> list[dict]:
        self._buf += data
        out: list[dict] = []
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            msg = _parse(line)
            if msg is not None:
                out.append(msg)
        if len(self._buf) > MAX_LINE:
            log.debug("dropping oversized partial line (%d bytes)", len(self._buf))
            self._buf = b""
        return out


def _parse(line: bytes) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        msg = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        log.debug("skipping non-JSON line: %r", line[:80])
        return None
    if not isinstance(msg, dict) or msg.get("v") != VERSION:
        log.debug("skipping line with wrong shape/version: %r", line[:80])
        return None
    return msg


def split_chunks(line: bytes, size: int) -> list[bytes]:
    if size < 1:
        raise ValueError("chunk size must be >= 1")
    return [line[i:i + size] for i in range(0, len(line), size)]


# ---- message builders -------------------------------------------------------

def board(sessions: list[dict], counts: dict) -> dict:
    return {"type": "board", "sessions": sessions, "counts": counts}


def alert(id: str) -> dict:
    return {"type": "alert", "id": id}


def hello_helper() -> dict:
    return {"type": "hello", "device": "helper"}


def hello_device(device: str, uid: str, transport: str, caps: dict) -> dict:
    return {"type": "hello", "device": device, "uid": uid, "transport": transport, "caps": caps}


def focus(id: str) -> dict:
    return {"type": "focus", "id": id}


def focus_next_waiting() -> dict:
    return {"type": "focus_next_waiting"}
