import pytest

from pitwall import config as c


def test_defaults_when_missing(tmp_path):
    cfg = c.load(tmp_path / "config.toml")
    assert cfg == c.Config(devices={"badger2350": ["usb", "ble"]}, agents=["claude-code"], terminal="iterm2")


def test_roundtrip(tmp_path):
    p = tmp_path / "config.toml"
    cfg = c.Config(devices={"badger2350": ["usb"]}, agents=["claude-code"], terminal="iterm2")
    c.save(cfg, p)
    assert c.load(p) == cfg
    assert "[devices.badger2350]" in p.read_text() and 'transports = ["usb"]' in p.read_text()


@pytest.mark.parametrize("text,msg", [
    ('[devices.nope]\ntransports = ["usb"]\n', "unknown device 'nope'"),
    ('[devices.badger2350]\ntransports = ["wifi"]\n', "unknown transport 'wifi' for badger2350"),
    ('terminal = "ghostty"\n', "unknown terminal 'ghostty'"),
    ('agents = ["codex"]\n', "unknown agent 'codex'"),
    ('devices = 3\n', "devices"),
    ("not = [toml", "isn't valid TOML"),
])
def test_invalid_config_is_explained(tmp_path, text, msg):
    p = tmp_path / "config.toml"
    p.write_text(text)
    with pytest.raises(c.ConfigError) as e:
        c.load(p)
    assert msg in str(e.value)


def test_parse_device_args():
    assert c.parse_device_args(["badger2350"]) == {"badger2350": ["usb", "ble"]}
    assert c.parse_device_args(["badger2350:usb"]) == {"badger2350": ["usb"]}
    assert c.parse_device_args(["badger2350:ble,usb"]) == {"badger2350": ["ble", "usb"]}
    with pytest.raises(c.ConfigError) as e:
        c.parse_device_args(["stream-deck"])
    assert "unknown device 'stream-deck'. Available: badger2350" in str(e.value)
    with pytest.raises(c.ConfigError):
        c.parse_device_args(["badger2350:carrier-pigeon"])


def test_watchers_follow_config():
    from pitwall.server import watchers_for
    names = lambda cfg: sorted(w.__name__ for w in watchers_for(cfg))
    full = c.Config({"badger2350": ["usb", "ble"]}, ["claude-code"], "iterm2")
    assert names(full) == ["ble_watcher", "title_watcher", "usb_watcher"]
    assert names(c.Config({"badger2350": ["usb"]}, ["claude-code"], "iterm2")) == ["title_watcher", "usb_watcher"]
    assert names(c.Config({}, ["claude-code"], "iterm2")) == ["title_watcher"]
