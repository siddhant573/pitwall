import asyncio

from pitwall import cli
from pitwall.render import fmt_age, render_board
from pitwall.server import serve

BOARD = {"v": 1, "type": "board", "counts": {"box": 1, "red": 0, "done": 1, "green": 1},
         "sessions": [
             {"id": "a", "label": "api", "state": "box", "age_s": 180, "focusable": True},
             {"id": "b", "label": "docs", "state": "done", "age_s": 30, "focusable": True},
             {"id": "c", "label": "web", "state": "green", "age_s": 5, "focusable": False}]}


def test_fmt_age():
    assert [fmt_age(s) for s in (5, 59, 60, 180, 3599, 3600, 3900)] == \
        ["5s", "59s", "1m", "3m", "59m", "1h00", "1h05"]


def test_render_board_contents_and_order():
    out = render_board(BOARD, cursor=1)
    assert "🟡" in out and "waiting 3m" in out
    assert out.index("api") < out.index("docs") < out.index("web")
    assert "🟡 1 · 🔴 0 · 🏁 1 · 🟢 1" in out
    lines = out.splitlines()
    assert any(l.startswith("›") and "docs" in l for l in lines)
    assert "waiting" not in [l for l in lines if "docs" in l][0]


def test_render_empty_board():
    assert "No agent sessions yet" in render_board({"sessions": [], "counts": {}})


def test_status_without_helper(monkeypatch, short_tmp, capsys):
    monkeypatch.setenv("PITWALL_HOME", str(short_tmp))
    assert cli.main(["status"]) == 1
    err = capsys.readouterr().err
    assert "pitwall helper isn't running" in err and "pitwall service status" in err


async def test_status_with_helper(monkeypatch, short_tmp, capsys):
    monkeypatch.setenv("PITWALL_HOME", str(short_tmp))
    task = asyncio.create_task(serve(short_tmp, watchers=[]))
    try:
        for _ in range(100):
            if (short_tmp / "devices.sock").is_socket():
                break
            await asyncio.sleep(0.02)
        assert await cli.status_async(short_tmp) == 0
        assert "No agent sessions yet" in capsys.readouterr().out
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_install_and_uninstall_claude_code(monkeypatch, tmp_path, capsys):
    p = tmp_path / "settings.json"
    monkeypatch.setattr(cli, "default_settings_path", lambda: p)
    assert cli.main(["install", "claude-code"]) == 0
    assert "pitwall-hook" in p.read_text()
    assert cli.main(["uninstall", "claude-code"]) == 0
    assert "pitwall-hook" not in p.read_text()


def test_install_claude_code_invalid_json(monkeypatch, tmp_path, capsys):
    p = tmp_path / "settings.json"
    p.write_text("{ nope")
    monkeypatch.setattr(cli, "default_settings_path", lambda: p)
    assert cli.main(["install", "claude-code"]) == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_render_shows_title_and_folder():
    b = {"counts": {}, "sessions": [{"id": "a", "label": "api", "title": "Fix login bug", "state": "green",
                                     "age_s": 1, "focusable": True}]}
    line = render_board(b).splitlines()[2]
    assert "Fix login bug" in line and "api" in line


def test_serve_device_flag_overrides_config(tmp_path):
    from pitwall import config as c
    p = tmp_path / "config.toml"
    c.save(c.Config({"badger2350": ["usb", "ble"]}, ["claude-code"], "iterm2"), p)
    assert cli.resolve_config(["badger2350:usb"], p).devices == {"badger2350": ["usb"]}
    assert cli.resolve_config([], p).devices == {"badger2350": ["usb", "ble"]}


def test_serve_unknown_device_exits_2(capsys):
    assert cli.main(["serve", "--device", "stream-deck"]) == 2
    assert "unknown device 'stream-deck'. Available: badger2350" in capsys.readouterr().err


def test_uninstall_all(monkeypatch, tmp_path, capsys):
    import pitwall.install_badge as ib
    import pitwall.links.usb as usb
    from pitwall import service
    home = tmp_path / ".pitwall"
    home.mkdir()
    (home / "config.toml").write_text("")
    monkeypatch.setenv("PITWALL_HOME", str(home))
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(cli, "default_settings_path", lambda: settings)
    cli.main(["install", "claude-code"])
    calls = []
    monkeypatch.setattr(service, "uninstall", lambda: calls.append("service") or True)
    monkeypatch.setattr(usb, "find_badge_ports", lambda: ["/dev/cu.usbmodem1"])
    monkeypatch.setattr(ib, "uninstall_badge", lambda port: calls.append(("badge", port)) or True)
    assert cli.main(["uninstall", "all"]) == 0
    assert calls == ["service", ("badge", "/dev/cu.usbmodem1")]
    assert "pitwall-hook" not in settings.read_text()
    assert not home.exists()
    assert "pipx uninstall pitwall-agents" in capsys.readouterr().out


def test_uninstall_all_without_badge(monkeypatch, tmp_path, capsys):
    import pitwall.links.usb as usb
    from pitwall import service
    monkeypatch.setenv("PITWALL_HOME", str(tmp_path / ".pitwall"))
    monkeypatch.setattr(cli, "default_settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(service, "uninstall", lambda: False)
    monkeypatch.setattr(usb, "find_badge_ports", lambda: [])
    assert cli.main(["uninstall", "all"]) == 0
    assert "pitwall uninstall badge" in capsys.readouterr().out


def test_serve_log_file_rotates(tmp_path):
    import logging.handlers
    h = cli.log_handler(tmp_path / "serve.log")
    assert isinstance(h, logging.handlers.RotatingFileHandler) and h.maxBytes == 1_000_000


def test_uninstall_all_survives_broken_settings(monkeypatch, tmp_path, capsys):
    import pitwall.links.usb as usb
    from pitwall import service
    home = tmp_path / ".pitwall"; home.mkdir()
    monkeypatch.setenv("PITWALL_HOME", str(home))
    bad = tmp_path / "settings.json"; bad.write_text("{ nope")
    monkeypatch.setattr(cli, "default_settings_path", lambda: bad)
    monkeypatch.setattr(service, "uninstall", lambda: True)
    monkeypatch.setattr(usb, "find_badge_ports", lambda: [])
    assert cli.main(["uninstall", "all"]) == 0
    assert "! Claude Code hooks:" in capsys.readouterr().out and not home.exists()
