from pathlib import Path

from pitwall import config as c
from pitwall import setup


def fake_env(**over):
    env = dict(badge_ports=["/dev/cu.usbmodem1"], which={"claude": "/bin/claude"},
               apps={"/Applications/iTerm.app"}, term_program="iTerm.app")
    env.update(over)
    return setup.Env(list_badges=lambda: env["badge_ports"], which=lambda n: env["which"].get(n),
                     exists=lambda p: str(p) in env["apps"], term_program=env["term_program"])


def test_detect_everything():
    d = setup.detect(fake_env())
    assert d.devices == {"badger2350": "connected over USB (/dev/cu.usbmodem1)"}
    assert d.agents == ["claude-code"] and d.terminal == "iterm2" and d.unsupported_terminal is None


def test_detect_nothing_and_unsupported_terminal():
    d = setup.detect(fake_env(badge_ports=[], which={}, apps=set(), term_program="ghostty"))
    assert d.devices == {} and d.agents == [] and d.terminal is None
    assert d.unsupported_terminal == "Ghostty"   # shown by its product name


def test_run_setup_yes_does_everything_in_order(tmp_path):
    calls = []
    steps = setup.Steps(install_agent=lambda a: calls.append(("agent", a)),
                        install_badge=lambda: calls.append(("badge",)),
                        install_service=lambda: calls.append(("service",)))
    cfg_path = tmp_path / "config.toml"
    rc = setup.run_setup(yes=True, env=fake_env(), steps=steps, config_file=cfg_path, out=lambda *a: None)
    assert rc == 0
    assert calls == [("agent", "claude-code"), ("badge",), ("service",)]
    assert c.load(cfg_path) == c.Config({"badger2350": ["usb", "ble"]}, ["claude-code"], "iterm2")


def test_run_setup_without_badge_skips_app_install_but_keeps_device(tmp_path):
    calls = []
    steps = setup.Steps(install_agent=lambda a: calls.append(a), install_badge=lambda: calls.append("badge"),
                        install_service=lambda: calls.append("service"))
    lines = []
    rc = setup.run_setup(yes=True, env=fake_env(badge_ports=[]), steps=steps,
                         config_file=tmp_path / "c.toml", out=lambda *a: lines.append(" ".join(map(str, a))))
    assert rc == 0 and "badge" not in calls and "service" in calls
    assert c.load(tmp_path / "c.toml").devices == {"badger2350": ["usb", "ble"]}
    assert any("pitwall install badge" in l for l in lines)


def test_run_setup_stops_without_supported_terminal(tmp_path):
    lines = []
    rc = setup.run_setup(yes=True, env=fake_env(apps=set(), term_program="Apple_Terminal"),
                         steps=setup.Steps(lambda a: None, lambda: None, lambda: None),
                         config_file=tmp_path / "c.toml", out=lambda *a: lines.append(" ".join(map(str, a))))
    assert rc == 1 and not (tmp_path / "c.toml").exists()
    assert any("iTerm2" in l for l in lines)


def test_run_setup_asks_and_respects_no(tmp_path):
    answers = iter(["n"])
    calls = []
    rc = setup.run_setup(yes=False, env=fake_env(), steps=setup.Steps(lambda a: calls.append(a), lambda: calls.append("b"), lambda: calls.append("s")),
                         config_file=tmp_path / "c.toml", out=lambda *a: None, ask=lambda q: next(answers))
    assert rc == 1 and calls == [] and not (tmp_path / "c.toml").exists()


def test_setup_keeps_going_when_badge_or_hooks_fail(tmp_path):
    from pitwall.agents.claude_settings import SettingsError
    from pitwall.install_badge import BadgeInstallError
    calls, lines = [], []

    def bad_agent(a):
        raise SettingsError("settings.json is not valid JSON")

    def bad_badge():
        raise BadgeInstallError("The BADGER drive didn't appear.")

    steps = setup.Steps(install_agent=bad_agent, install_badge=bad_badge,
                        install_service=lambda: calls.append("service"))
    rc = setup.run_setup(yes=True, env=fake_env(), steps=steps, config_file=tmp_path / "c.toml",
                         out=lambda *a: lines.append(" ".join(map(str, a))))
    assert rc == 1 and calls == ["service"]
    text = "\n".join(lines)
    assert "! claude-code hooks: settings.json is not valid JSON" in text
    assert "! badge: The BADGER drive didn't appear." in text
    assert "pitwall install claude-code" in text and "pitwall install badge" in text


def test_setup_plan_is_numbered_in_order(tmp_path):
    lines = []
    setup.run_setup(yes=True, env=fake_env(badge_ports=[]), steps=setup.Steps(lambda a: None, lambda: None, lambda: None),
                    config_file=tmp_path / "c.toml", out=lambda *a: lines.append(" ".join(map(str, a))))
    nums = [l.strip()[:2] for l in lines if l.strip()[:2] in ("1.", "2.", "3.", "4.")]
    assert nums == ["1.", "2.", "3."]
    assert not any("Open Pitwall from the badge" in l for l in lines)


def test_detect_iterm_in_user_applications():
    home_app = str(Path.home() / "Applications" / "iTerm.app")
    d = setup.detect(fake_env(apps={home_app}, term_program=None))
    assert d.terminal == "iterm2"
