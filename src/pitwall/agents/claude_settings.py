"""Add or remove pitwall's hooks in Claude Code's settings.json, safely."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PermissionRequest",
          "Notification", "Stop", "StopFailure", "SessionEnd")
_MATCHER_EVENTS = {"PreToolUse", "PostToolUse", "PermissionRequest"}


class SettingsError(Exception):
    pass


@dataclass
class InstallResult:
    changed: bool
    backup: Path | None


def default_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def hook_command() -> str:
    """An absolute path to `pitwall-hook`, so hooks work whatever PATH Claude Code has."""
    return shutil.which("pitwall-hook") or str(Path(sys.executable).parent / "pitwall-hook")


def _is_pitwall(cmd: str) -> bool:
    return "pitwall-hook" in cmd


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text() or "{}")
    except ValueError as e:
        raise SettingsError(f"{path} is not valid JSON ({e}); fix it first, nothing was changed") from e
    if not isinstance(data, dict):
        raise SettingsError(f"{path} must contain a JSON object; nothing was changed")
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise SettingsError(f'"hooks" in {path} must be an object; nothing was changed')
    return data


def _strip(hooks: dict) -> dict:
    """Return hooks with every pitwall command removed (and emptied entries dropped)."""
    out = {}
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            out[event] = entries
            continue
        kept = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                kept.append(entry)
                continue
            inner = [h for h in entry["hooks"]
                     if not (isinstance(h, dict) and _is_pitwall(str(h.get("command", ""))))]
            if inner:
                kept.append({**entry, "hooks": inner})
            elif not entry["hooks"]:
                kept.append(entry)
        if kept:
            out[event] = kept
    return out


def _write(path: Path, original: str | None, data: dict) -> Path | None:
    link = path
    path = path.resolve()  # keep a symlinked settings.json a symlink (dotfiles)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    backup = None
    if original is not None:
        backup = link.with_name(f"{link.name}.pitwall-bak-{time.strftime('%Y%m%d-%H%M%S')}")
        backup.write_text(original)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    return backup


def install(settings_path: Path, command: str) -> InstallResult:
    data = _load(settings_path)
    original = settings_path.read_text() if settings_path.exists() else None
    hooks = _strip(data.get("hooks", {}))
    for event in EVENTS:
        entry: dict = {"hooks": [{"type": "command", "command": command, "timeout": 5}]}
        if event in _MATCHER_EVENTS:
            entry = {"matcher": "", **entry}
        hooks.setdefault(event, []).append(entry)
    new = {**data, "hooks": hooks}
    if new == data:
        return InstallResult(False, None)
    return InstallResult(True, _write(settings_path, original, new))


def uninstall(settings_path: Path) -> InstallResult:
    if not settings_path.exists():
        return InstallResult(False, None)
    data = _load(settings_path)
    original = settings_path.read_text()
    hooks = _strip(data.get("hooks", {}))
    new = {**data, "hooks": hooks} if hooks else {k: v for k, v in data.items() if k != "hooks"}
    if new == data:
        return InstallResult(False, None)
    return InstallResult(True, _write(settings_path, original, new))
