"""Claude Code hooks → pitwall session events.

Only ids, the folder and the terminal tab leave this module. Prompts, tool input
and output, and assistant messages are never read.
"""
from __future__ import annotations

import os
from typing import Mapping

AGENT = "claude-code"

_EVENT_STATE = {
    "UserPromptSubmit": "green",
    "PreToolUse": "green",
    "PostToolUse": "green",
    "PermissionRequest": "box",
    "Stop": "done",
    "StopFailure": "red",
    "SessionStart": "done",
    "SessionEnd": "end",
}
_NOTIFICATION_STATE = {"permission_prompt": "box", "elicitation_dialog": "box",
                       # Stop doesn't run when the user interrupts a turn; idle_prompt covers it
                       "idle_prompt": "done"}


def iterm_ref(env: Mapping[str, str]) -> dict | None:
    raw = env.get("ITERM_SESSION_ID") or ""
    ref = raw.split(":", 1)[-1].strip()
    return {"kind": "iterm2", "ref": ref} if ref else None


def map_hook(payload: dict, env: Mapping[str, str]) -> dict | None:
    if not isinstance(payload, dict):
        return None
    sid = payload.get("session_id")
    event = payload.get("hook_event_name")
    if not isinstance(sid, str) or not sid:
        return None
    if event == "Notification":
        state = _NOTIFICATION_STATE.get(payload.get("notification_type"))
    else:
        state = _EVENT_STATE.get(event)
    if state is None:
        return None
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else ""
    label = os.path.basename(cwd.rstrip("/")) or "session"
    return {"type": "session", "agent": AGENT, "id": sid, "state": state,
            "label": label, "cwd": cwd, "terminal": iterm_ref(env)}
