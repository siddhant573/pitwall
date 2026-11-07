"""Focus an iTerm2 session by its unique id, via AppleScript."""
from __future__ import annotations

import re
import subprocess

# The ref is passed as argv, never interpolated into the script.
SCRIPT = """
on run argv
    set target to item 1 of argv
    if not (application "iTerm2" is running) then return "not_running"
    tell application "iTerm2"
        repeat with w in windows
            repeat with t in tabs of w
                repeat with s in sessions of t
                    if (unique id of s) is target then
                        select w
                        tell t to select
                        tell s to select
                        activate
                        return "ok"
                    end if
                end repeat
            end repeat
        end repeat
    end tell
    return "missing"
end run
"""


def focus(ref: str, run=subprocess.run) -> str:
    """"ok", "missing" (no such tab) or "error" (iTerm2 not running, permission, timeout…)."""
    try:
        r = run(["osascript", "-", ref], input=SCRIPT, capture_output=True, text=True, timeout=3)
    except (subprocess.TimeoutExpired, OSError):
        return "error"
    out = r.stdout.strip() if r.returncode == 0 else ""
    return out if out in ("ok", "missing") else "error"


TITLES_SCRIPT = """
if not (application "iTerm2" is running) then return "not_running"
set sep to (ASCII character 9)
set out to ""
tell application "iTerm2"
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                set out to out & (unique id of s) & sep & (name of s) & linefeed
            end repeat
        end repeat
    end repeat
end tell
return out
"""

# Claude Code puts a status glyph in front of the title (✳ idle, spinners while working)
_LEAD = re.compile(r"^[^\w~/(\[\"']+\s*")
_PROC = re.compile(r"\s*\([^()]*\)\s*$")       # iTerm's " (-zsh)" / " (claude)" job suffix
_DEFAULTS = {"claude code", "claude", "-zsh", "zsh", "bash", "-bash"}


def clean_title(name: str) -> str | None:
    t = _PROC.sub("", _LEAD.sub("", (name or "").strip())).strip()
    if not t or t.lower() in _DEFAULTS or t.startswith(("~", "/")):
        return None
    return t


def titles(run=subprocess.run) -> dict[str, str | None]:
    """Session unique id -> cleaned tab title, for every iTerm2 session. {} if unavailable."""
    try:
        r = run(["osascript", "-"], input=TITLES_SCRIPT, capture_output=True, text=True, timeout=3)
    except (subprocess.TimeoutExpired, OSError):
        return {}
    if r.returncode != 0:
        return {}
    out = {}
    for line in r.stdout.splitlines():
        if "\t" in line:
            ref, name = line.split("\t", 1)
            out[ref.strip()] = clean_title(name)
    return out
