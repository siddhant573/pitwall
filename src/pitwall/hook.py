"""`pitwall-hook`: called by agent hooks. Must be fast, silent, and always exit 0.

Stdlib only. Don't import serial/bleak/asyncio here.
"""
from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import BinaryIO, Mapping

from .agents.claude_code import map_hook


def run_hook(stdin: BinaryIO, env: Mapping[str, str], sock_path: Path, timeout_s: float = 0.2) -> int:
    try:
        payload = json.loads(stdin.read().decode("utf-8"))
        event = map_hook(payload, env)
        if event is None:
            return 0
        event["v"] = 1
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.settimeout(timeout_s)
            s.connect(str(sock_path))
            s.sendall(line)
        finally:
            s.close()
    except Exception:
        pass
    return 0


def main() -> int:
    from .paths import hook_socket
    return run_hook(sys.stdin.buffer, os.environ, hook_socket())


if __name__ == "__main__":
    sys.exit(main())
