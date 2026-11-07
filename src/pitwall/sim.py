"""`pitwall sim`: a fake device in the terminal, talking the real protocol over devices.sock."""
from __future__ import annotations

import asyncio
import os
import sys
import termios
import tty
from pathlib import Path

from . import paths, protocol
from .render import render_board


def sim_key(key: str, sessions: list[dict], cursor: int) -> tuple[int, dict | None]:
    last = max(0, len(sessions) - 1)
    if key == "up":
        return max(0, cursor - 1), None
    if key == "down":
        return min(last, cursor + 1), None
    if key == "n":
        return cursor, protocol.focus_next_waiting()
    if key == "enter":
        if sessions:
            return cursor, protocol.focus(sessions[min(cursor, last)]["id"])
        return cursor, None
    return cursor, None


def _read_key(fd: int) -> str:
    ch = os.read(fd, 3)
    return {b"\x1b[A": "up", b"\x1b[B": "down", b"\r": "enter", b"\n": "enter",
            b"n": "n", b"q": "q", b"\x03": "q"}.get(ch, "")


async def run_sim(home: Path | None = None) -> int:
    try:
        reader, writer = await asyncio.open_unix_connection(str(paths.device_socket(home)))
    except (FileNotFoundError, ConnectionRefusedError):
        from .cli import NOT_RUNNING
        print(NOT_RUNNING, file=sys.stderr)
        return 1
    writer.write(protocol.encode(protocol.hello_device(
        "sim", f"sim-{os.getpid()}", "socket",
        {"display": [80, 24], "color": True, "buttons": ["up", "down", "enter", "n"], "keys": 0, "led": False})))
    await writer.drain()
    state = {"board": {"sessions": [], "counts": {}}, "cursor": 0}
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    loop = asyncio.get_running_loop()
    keys: asyncio.Queue[str] = asyncio.Queue()
    loop.add_reader(fd, lambda: keys.put_nowait(_read_key(fd)))

    def draw() -> None:
        sys.stdout.write("\x1b[2J\x1b[H" + render_board(state["board"], state["cursor"]).replace("\n", "\r\n")
                         + "\r\n\r\n↑/↓ move · enter focus · n next box box · q quit\r\n")
        sys.stdout.flush()

    async def inbound() -> None:
        dec = protocol.LineDecoder()
        while data := await reader.read(4096):
            for m in dec.feed(data):
                if m.get("type") == "board":
                    state["board"] = m
                    state["cursor"] = min(state["cursor"], max(0, len(m.get("sessions") or []) - 1))
                    draw()
                elif m.get("type") == "alert":
                    sys.stdout.write("\a")
                    sys.stdout.flush()

    try:
        tty.setcbreak(fd)
        task = asyncio.create_task(inbound())
        draw()
        while True:
            getter = asyncio.ensure_future(keys.get())
            await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
            if task.done():  # the helper went away
                getter.cancel()
                break
            key = getter.result()
            if key == "q":
                break
            state["cursor"], msg = sim_key(key, state["board"].get("sessions") or [], state["cursor"])
            if msg:
                writer.write(protocol.encode(msg))
                await writer.drain()
            draw()
        task.cancel()
    finally:
        loop.remove_reader(fd)
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        writer.close()
    return 0
