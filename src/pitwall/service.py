"""Keep `pitwall serve` running with a launchd LaunchAgent (runs as you, after login)."""
from __future__ import annotations

import contextlib
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths

LABEL = "io.github.siddhant573.pitwall"


class ServiceError(Exception):
    pass


def program_path() -> str:
    """An absolute path to the `pitwall` command (launchd doesn't search PATH)."""
    found = shutil.which("pitwall")
    if found:
        return found
    beside = Path(sys.executable).parent / "pitwall"
    return str(beside if beside.exists() else Path(sys.argv[0]).resolve())


def _agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path(agents_dir: Path | None = None) -> Path:
    return (agents_dir or _agents_dir()) / f"{LABEL}.plist"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def plist(program: str, log: Path) -> bytes:
    out = log.with_suffix(".out")  # only crash output lands here; the log itself is rotated
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [program, "serve", "--log-file", str(log)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Interactive",
        "StandardOutPath": str(out),
        "StandardErrorPath": str(out),
        "EnvironmentVariables": {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"},
    })


def install(program: str | None = None, agents_dir: Path | None = None, run=subprocess.run) -> Path:
    program = program or program_path()
    p = plist_path(agents_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(plist(program, paths.ensure_home() / "serve.log"))
    run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], capture_output=True, text=True)
    r = run(["launchctl", "bootstrap", _domain(), str(p)], capture_output=True, text=True)
    if r.returncode != 0:
        raise ServiceError(f"launchctl couldn't start the service ({(r.stderr or '').strip() or r.returncode}). "
                           f"Try `pitwall serve -v` to see why.")
    return p


def uninstall(agents_dir: Path | None = None, run=subprocess.run) -> bool:
    p = plist_path(agents_dir)
    if not p.exists():
        return False
    run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], capture_output=True, text=True)
    p.unlink()
    return True


def _pid(run) -> int | None:
    r = run(["launchctl", "print", f"{_domain()}/{LABEL}"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    m = re.search(r"\bpid = (\d+)", r.stdout or "")
    return int(m.group(1)) if m else None


def status(agents_dir: Path | None = None, run=subprocess.run) -> str:
    if not plist_path(agents_dir).exists():
        return "not installed"
    pid = _pid(run)
    return f"running (pid {pid})" if pid else "installed, not running"


def restart(run=subprocess.run) -> None:
    run(["launchctl", "kickstart", "-k", f"{_domain()}/{LABEL}"], capture_output=True, text=True)


@contextlib.contextmanager
def paused(agents_dir: Path | None = None, run=subprocess.run):
    """Stop the service for a moment (e.g. to free the badge's USB port), then start it again."""
    was_running = plist_path(agents_dir).exists() and _pid(run) is not None
    if was_running:
        run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], capture_output=True, text=True)
    try:
        yield was_running
    finally:
        if was_running:
            run(["launchctl", "bootstrap", _domain(), str(plist_path(agents_dir))], capture_output=True, text=True)
