"""Helper-side storage of paired badges."""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from . import paths


def host_id(home: Path | None = None) -> str:
    """A stable random id for this Mac, created on first use."""
    home = paths.ensure_home(home)
    p = home / "host_id"
    if p.exists():
        v = p.read_text().strip()
        if v:
            return v
    v = secrets.token_hex(8)
    p.write_text(v)
    os.chmod(p, 0o600)
    return v


class PairingStore:
    def __init__(self, path: Path | None = None):
        self.path = path or paths.home_dir() / "pairing.json"

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)
        os.chmod(self.path, 0o600)

    def all(self) -> dict:
        return self._load()

    def get(self, uid: str) -> dict | None:
        return self._load().get(uid)

    def add(self, uid: str, data: dict) -> None:
        d = self._load()
        d[uid] = data
        self._save(d)
