import pytest

from conftest import load
from pitwall.agents.claude_code import iterm_ref, map_hook

ENV = {"ITERM_SESSION_ID": "w0t1p0:ABC-123"}


@pytest.mark.parametrize("fixture,state", [
    ("UserPromptSubmit", "green"), ("PreToolUse", "green"), ("PostToolUse", "green"),
    ("PermissionRequest", "box"), ("Notification_permission_prompt", "box"),
    ("Stop", "done"), ("StopFailure", "red"), ("SessionStart", "done"), ("SessionEnd", "end")])
def test_mapping(fixture, state):
    ev = map_hook(load(fixture), ENV)
    assert ev["state"] == state
    assert ev["terminal"] == {"kind": "iterm2", "ref": "ABC-123"}
    assert ev["agent"] == "claude-code"
    assert ev["id"] == "11111111-2222-3333-4444-555555555555"
    assert ev["label"] == "api" and ev["cwd"] == "/Users/dev/work/api"


def test_elicitation_is_box():
    p = load("Notification_permission_prompt") | {"notification_type": "elicitation_dialog"}
    assert map_hook(p, ENV)["state"] == "box"


def test_idle_prompt_means_done():
    # Claude doesn't run Stop when the user interrupts a turn; idle_prompt covers it
    assert map_hook(load("Notification_idle_prompt"), ENV)["state"] == "done"


@pytest.mark.parametrize("ntype", ["auth_success", None])
def test_other_notifications_change_nothing(ntype):
    p = load("Notification_idle_prompt") | {"notification_type": ntype}
    assert map_hook(p, ENV) is None


def test_unknown_event_and_missing_session_id():
    assert map_hook({"hook_event_name": "PreCompact", "session_id": "x"}, ENV) is None
    assert map_hook({"hook_event_name": "Stop"}, ENV) is None
    assert map_hook("not a dict", ENV) is None


def test_event_carries_no_content():
    ev = map_hook(load("PreToolUse"), {})
    assert set(ev) == {"type", "agent", "id", "state", "label", "cwd", "terminal"}
    assert "<redacted>" not in repr(ev)


def test_iterm_ref():
    assert iterm_ref({"ITERM_SESSION_ID": "w0t1p0:ABC"}) == {"kind": "iterm2", "ref": "ABC"}
    assert iterm_ref({"ITERM_SESSION_ID": "ABC"}) == {"kind": "iterm2", "ref": "ABC"}
    assert iterm_ref({}) is None
    assert iterm_ref({"ITERM_SESSION_ID": ""}) is None
