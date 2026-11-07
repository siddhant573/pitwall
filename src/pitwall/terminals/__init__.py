"""Terminal plug-ins: bring a session's tab to the front."""
from __future__ import annotations

from . import iterm2


def focus(terminal: dict | None) -> str:
    """"ok", "missing" (the tab is gone) or "error" (couldn't tell)."""
    if not isinstance(terminal, dict) or not terminal.get("ref"):
        return "error"
    if terminal.get("kind") == "iterm2":
        return iterm2.focus(str(terminal["ref"]))
    return "error"
