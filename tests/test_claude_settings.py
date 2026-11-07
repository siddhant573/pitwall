import json
from pathlib import Path

import pytest

from pitwall.agents.claude_settings import EVENTS, SettingsError, install, uninstall

CMD = "/usr/local/bin/pitwall-hook"


def read(p):
    return json.loads(p.read_text())


def pitwall_cmds(data, event):
    return [h["command"] for e in data["hooks"].get(event, []) for h in e.get("hooks", [])
            if "pitwall" in h.get("command", "")]


def test_install_creates_file_when_missing(tmp_path):
    p = tmp_path / ".claude" / "settings.json"
    r = install(p, CMD)
    assert r.changed and r.backup is None
    data = read(p)
    for ev in EVENTS:
        assert pitwall_cmds(data, ev) == [CMD]
    stop = data["hooks"]["Stop"][0]
    assert "matcher" not in stop and stop["hooks"][0] == {"type": "command", "command": CMD, "timeout": 5}
    assert data["hooks"]["PreToolUse"][0]["matcher"] == ""


def test_install_is_idempotent(tmp_path):
    p = tmp_path / "settings.json"
    install(p, CMD)
    before = p.read_text()
    r = install(p, CMD)
    assert r.changed is False and r.backup is None
    assert p.read_text() == before


def test_install_preserves_existing_hooks_and_keys(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}))
    install(p, CMD)
    data = read(p)
    assert data["model"] == "x"
    cmds = [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]]
    assert cmds == ["say done", CMD]


def test_backup_written_before_change(tmp_path):
    p = tmp_path / "settings.json"
    original = json.dumps({"model": "x"})
    p.write_text(original)
    r = install(p, CMD)
    assert r.backup is not None and r.backup.read_text() == original
    assert r.backup.name.startswith("settings.json.pitwall-bak-")


def test_refuses_invalid_json(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{ nope")
    with pytest.raises(SettingsError):
        install(p, CMD)
    assert p.read_text() == "{ nope"
    assert list(tmp_path.iterdir()) == [p]


def test_refuses_non_object_hooks(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": []}))
    with pytest.raises(SettingsError):
        install(p, CMD)


def test_reinstall_with_new_path_replaces_old_entry(tmp_path):
    p = tmp_path / "settings.json"
    install(p, "/old/pitwall-hook")
    install(p, CMD)
    assert pitwall_cmds(read(p), "Stop") == [CMD]


def test_uninstall_removes_only_pitwall_entries(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}))
    install(p, CMD)
    r = uninstall(p)
    assert r.changed
    data = read(p)
    assert data["hooks"] == {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}
    assert uninstall(p).changed is False


def test_uninstall_missing_file_is_noop(tmp_path):
    assert uninstall(tmp_path / "nope.json").changed is False


def test_symlinked_settings_stay_a_symlink(tmp_path):
    real = tmp_path / "dotfiles" / "settings.json"
    real.parent.mkdir()
    real.write_text(json.dumps({"model": "x"}))
    real.chmod(0o644)
    link = tmp_path / ".claude" / "settings.json"
    link.parent.mkdir()
    link.symlink_to(real)
    install(link, CMD)
    assert link.is_symlink()
    assert "pitwall-hook" in real.read_text()
    assert (real.stat().st_mode & 0o777) == 0o644


def test_hook_command_falls_back_next_to_python(monkeypatch, tmp_path):
    import sys
    from pitwall.agents import claude_settings as cs
    monkeypatch.setattr(cs.shutil, "which", lambda n: None)
    assert cs.hook_command() == str(Path(sys.executable).parent / "pitwall-hook")
