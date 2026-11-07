"""`pitwall install badge`: copy the badge app over USB disk mode."""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

from .links.usb import find_badge_ports

VOLUME = Path("/Volumes/BADGER")
APP_FILES = ("__init__.py", "model.py", "links.py", "icon.png")

NO_BADGE = "No badge found. Plug it in over USB with a data cable, wake it, and try again."
BUSY = ("The badge's USB port is in use (is 'pitwall serve' running?). "
        "Stop it, run this again, then restart it.")
NO_VOLUME = "The BADGER drive didn't appear. Double-tap the badge's reset button, then run this again."


class BadgeInstallError(Exception):
    pass


def badge_app_dir() -> Path:
    """The badge app files: packaged copy if installed, else the repo's badge/pitwall."""
    here = Path(__file__).parent
    packaged = here / "badge_app"
    return packaged if packaged.is_dir() else here.parent.parent / "badge" / "pitwall"


def _mpremote(port: str, code: str) -> list[str]:
    return [sys.executable, "-m", "mpremote", "connect", port, "exec", "--no-follow", code]


def install_badge(port: str | None, volume: Path = VOLUME, run=subprocess.run, sleep=time.sleep,
                  wait_s: int = 30) -> None:
    apps = volume / "apps"
    if not apps.is_dir():
        if port is None:
            ports = find_badge_ports()
            if not ports:
                raise BadgeInstallError(NO_BADGE)
            port = ports[0]
        print(f"Badge on {port}, switching it to USB disk mode…")
        r = run(_mpremote(port, "import powman; powman.reset_into_msc()"),
                capture_output=True, text=True, timeout=30)
        err = (r.stderr or "") + (r.stdout or "")
        if r.returncode != 0 and any(w in err.lower() for w in ("in use", "busy", "failed to access", "could not")):
            raise BadgeInstallError(BUSY)
        for _ in range(wait_s):
            if apps.is_dir():
                break
            sleep(1)
        if not apps.is_dir():
            raise BadgeInstallError(NO_VOLUME)

    src = badge_app_dir()
    dest = apps / "pitwall"
    dest.mkdir(parents=True, exist_ok=True)
    for name in APP_FILES:
        shutil.copyfile(src / name, dest / name)
    shutil.copyfile(Path(__file__).parent / "seal.py", dest / "seal.py")
    run(["sync"], capture_output=True)
    run(["diskutil", "eject", str(volume)], capture_output=True)
    print("Pitwall is installed on the badge. It restarts; open \"Pitwall\" from its home menu.")


_REMOVE_KEYS = "import os\ntry:\n    os.remove('/state/pitwall_keys.json')\nexcept OSError:\n    pass"


def _remove_keys(port: str, run) -> None:
    r = run(_mpremote(port, _REMOVE_KEYS), capture_output=True, text=True, timeout=30)
    err = (r.stderr or "") + (r.stdout or "")
    if r.returncode != 0 and any(w in err.lower() for w in ("in use", "busy", "failed to access", "could not")):
        raise BadgeInstallError(BUSY)


def uninstall_badge(port: str | None, volume: Path = VOLUME, run=subprocess.run, sleep=time.sleep,
                    wait_s: int = 30) -> bool:
    """Remove the Pitwall app and its Bluetooth keys from the badge. Returns True if the app was there."""
    apps = volume / "apps"
    keys_done = False
    if not apps.is_dir():
        if port is None:
            ports = find_badge_ports()
            if not ports:
                raise BadgeInstallError(NO_BADGE)
            port = ports[0]
        _remove_keys(port, run)     # /state isn't on the disk-mode drive, so do it over the REPL first
        keys_done = True
        run(_mpremote(port, "import powman; powman.reset_into_msc()"), capture_output=True, text=True, timeout=30)
        for _ in range(wait_s):
            if apps.is_dir():
                break
            sleep(1)
        if not apps.is_dir():
            raise BadgeInstallError(NO_VOLUME)
    app = apps / "pitwall"
    removed = app.exists()
    if removed:
        shutil.rmtree(app)
    run(["sync"], capture_output=True)
    run(["diskutil", "eject", str(volume)], capture_output=True)
    if not keys_done:               # started in disk mode: remove the keys once the badge is back
        for _ in range(wait_s):
            ports = find_badge_ports()
            if ports:
                sleep(2)
                _remove_keys(ports[0], run)
                break
            sleep(1)
    return removed
