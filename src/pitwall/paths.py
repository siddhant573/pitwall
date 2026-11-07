"""Where pitwall keeps its sockets and state."""
from __future__ import annotations

import os
from pathlib import Path


def home_dir() -> Path:
    return Path(os.environ.get("PITWALL_HOME") or Path.home() / ".pitwall")


def hook_socket(home: Path | None = None) -> Path:
    return (home or home_dir()) / "pitwall.sock"


def device_socket(home: Path | None = None) -> Path:
    return (home or home_dir()) / "devices.sock"


def ensure_home(home: Path | None = None) -> Path:
    h = home or home_dir()
    h.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(h, 0o700)
    return h
