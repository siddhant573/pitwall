import shutil
import subprocess

import pytest

from pitwall import install_badge as ib

FILES = {"__init__.py", "model.py", "links.py", "seal.py", "icon.png"}


class FakeRun:
    def __init__(self, volume, code=0, stderr="", mount=True):
        self.volume, self.code, self.stderr, self.mount, self.calls = volume, code, stderr, mount, []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        if "reset_into_msc()" in " ".join(argv) and self.mount and self.code == 0:
            (self.volume / "apps" / "menu").mkdir(parents=True, exist_ok=True)
            (self.volume / "apps" / "menu" / "app.py").write_text("ORIGINAL MENU")
        return subprocess.CompletedProcess(argv, self.code, stdout="", stderr=self.stderr)


def test_copies_app_and_never_touches_menu(tmp_path):
    vol = tmp_path / "BADGER"
    run = FakeRun(vol)
    ib.install_badge("/dev/cu.usbmodem1", volume=vol, run=run, sleep=lambda s: None)
    assert {p.name for p in (vol / "apps" / "pitwall").iterdir()} == FILES
    assert (vol / "apps" / "menu" / "app.py").read_text() == "ORIGINAL MENU"
    assert any(a[:2] == ["diskutil", "eject"] for a in run.calls)


def test_no_badge(tmp_path, monkeypatch):
    monkeypatch.setattr(ib, "find_badge_ports", lambda: [])
    with pytest.raises(ib.BadgeInstallError) as e:
        ib.install_badge(None, volume=tmp_path / "BADGER", run=FakeRun(tmp_path), sleep=lambda s: None)
    assert str(e.value) == "No badge found. Plug it in over USB with a data cable, wake it, and try again."


def test_port_busy(tmp_path):
    run = FakeRun(tmp_path / "BADGER", code=1, stderr="mpremote: failed to access /dev/cu.usbmodem1 (it may be in use by another program)")
    with pytest.raises(ib.BadgeInstallError) as e:
        ib.install_badge("/dev/cu.usbmodem1", volume=tmp_path / "BADGER", run=run, sleep=lambda s: None)
    assert str(e.value) == ("The badge's USB port is in use (is 'pitwall serve' running?). "
                            "Stop it, run this again, then restart it.")


def test_volume_never_appears(tmp_path):
    run = FakeRun(tmp_path / "BADGER", mount=False)
    with pytest.raises(ib.BadgeInstallError) as e:
        ib.install_badge("/dev/cu.usbmodem1", volume=tmp_path / "BADGER", run=run, sleep=lambda s: None)
    assert str(e.value) == "The BADGER drive didn't appear. Double-tap the badge's reset button, then run this again."


def test_already_in_disk_mode_skips_reset(tmp_path):
    vol = tmp_path / "BADGER"
    (vol / "apps").mkdir(parents=True)
    run = FakeRun(vol)
    ib.install_badge(None, volume=vol, run=run, sleep=lambda s: None)
    assert not any("reset_into_msc()" in " ".join(a) for a in run.calls)
    assert (vol / "apps" / "pitwall" / "seal.py").exists()


def test_install_does_not_tell_people_to_run_serve(tmp_path, capsys):
    vol = tmp_path / "BADGER"
    ib.install_badge("/dev/cu.usbmodem1", volume=vol, run=FakeRun(vol), sleep=lambda s: None)
    assert "pitwall serve" not in capsys.readouterr().out


class MountingRun(FakeRun):
    """Like a real badge: disk mode mounts the drive with the app on it; eject unmounts it."""

    def __init__(self, volume, ports_after_eject=True):
        super().__init__(volume)

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        joined = " ".join(argv)
        if "reset_into_msc()" in joined:
            (self.volume / "apps" / "menu").mkdir(parents=True, exist_ok=True)
            (self.volume / "apps" / "menu" / "app.py").write_text("ORIGINAL MENU")
            (self.volume / "apps" / "pitwall").mkdir(exist_ok=True)
            (self.volume / "apps" / "pitwall" / "__init__.py").write_text("x")
        if argv[:2] == ["diskutil", "eject"]:
            menu = self.volume / "apps" / "menu" / "app.py"
            self.ejected_menu = menu.read_text() if menu.exists() else None
            self.ejected_has_app = (self.volume / "apps" / "pitwall").exists()
            shutil.rmtree(self.volume)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def test_uninstall_removes_app_and_keys_but_not_menu(tmp_path):
    vol = tmp_path / "BADGER"
    run = MountingRun(vol)
    assert ib.uninstall_badge("/dev/cu.usbmodem1", volume=vol, run=run, sleep=lambda s: None) is True
    assert run.ejected_has_app is False and run.ejected_menu == "ORIGINAL MENU"
    joined = [" ".join(a) for a in run.calls]
    keys = next(i for i, j in enumerate(joined) if "pitwall_keys.json" in j)
    msc = next(i for i, j in enumerate(joined) if "reset_into_msc()" in j)
    assert keys < msc


def test_uninstall_from_disk_mode_removes_keys_after_restart(tmp_path, monkeypatch):
    vol = tmp_path / "BADGER"
    (vol / "apps" / "pitwall").mkdir(parents=True)
    run = MountingRun(vol)
    monkeypatch.setattr(ib, "find_badge_ports", lambda: ["/dev/cu.usbmodem1"])
    assert ib.uninstall_badge(None, volume=vol, run=run, sleep=lambda s: None) is True
    joined = [" ".join(a) for a in run.calls]
    eject = next(i for i, j in enumerate(joined) if j.startswith("diskutil eject"))
    keys = next(i for i, j in enumerate(joined) if "pitwall_keys.json" in j)
    assert eject < keys


def test_uninstall_when_nothing_installed(tmp_path):
    vol = tmp_path / "BADGER"
    (vol / "apps").mkdir(parents=True)
    assert ib.uninstall_badge(None, volume=vol, run=FakeRun(vol), sleep=lambda s: None) is False
