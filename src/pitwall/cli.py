"""pitwall command line."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from . import __version__, paths, protocol
from .agents.claude_settings import SettingsError, default_settings_path, hook_command, install, uninstall
from .render import render_board

NOT_RUNNING = ("pitwall helper isn't running. Check `pitwall service status` "
               "(or run `pitwall serve` if you didn't run `pitwall setup`).")


async def status_async(home: Path | None = None) -> int:
    try:
        reader, writer = await asyncio.open_unix_connection(str(paths.device_socket(home)))
    except (FileNotFoundError, ConnectionRefusedError):
        print(NOT_RUNNING, file=sys.stderr)
        return 1
    writer.write(protocol.encode(protocol.hello_device("status", f"status-{os.getpid()}", "socket", {})))
    await writer.drain()
    dec = protocol.LineDecoder()
    try:
        async def first_board() -> dict:
            while data := await reader.read(4096):
                for m in dec.feed(data):
                    if m.get("type") == "board":
                        return m
            raise ConnectionError
        board = await asyncio.wait_for(first_board(), 3)
    except (asyncio.TimeoutError, ConnectionError):
        print(NOT_RUNNING, file=sys.stderr)
        return 1
    finally:
        writer.close()
    print(render_board(board))
    return 0


def log_handler(path: Path) -> logging.Handler:
    import logging.handlers
    path.parent.mkdir(parents=True, exist_ok=True)
    return logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=1)


def resolve_config(device_args: list[str], path: Path | None = None):
    from . import config
    cfg = config.load(path)
    if device_args:
        cfg.devices = config.parse_device_args(device_args)
    return cfg


def _cmd_service(action: str) -> int:
    from . import service
    if action == "install":
        print(f"LaunchAgent installed: {service.install()}")
    elif action == "uninstall":
        print("LaunchAgent removed." if service.uninstall() else "LaunchAgent wasn't installed.")
    elif action == "restart":
        service.restart()
    print(f"pitwall service: {service.status()}")
    return 0


def _uninstall_all() -> int:
    import shutil
    from . import service
    from .install_badge import BadgeInstallError
    from .links import usb
    print("✓ background service removed" if service.uninstall() else "• no background service")
    try:
        r = uninstall(default_settings_path())
        print("✓ Claude Code hooks removed" if r.changed else "• no Claude Code hooks")
    except SettingsError as e:
        print(f"! Claude Code hooks: {e}")
    ports = usb.find_badge_ports()
    if ports:
        from . import install_badge
        try:
            removed = install_badge.uninstall_badge(ports[0])
            print("✓ Pitwall app and keys removed from the badge" if removed else "• badge had no Pitwall app")
        except BadgeInstallError as e:
            print(f"! badge: {e}")
    else:
        print("• badge not connected: plug it in and run `pitwall uninstall badge` to remove the app")
    home = paths.home_dir()
    if home.exists():
        shutil.rmtree(home)
        print(f"✓ removed {home}")
    print("\nLast step: pipx uninstall pitwall-agents")
    return 0


def _cmd_install(target: str, remove: bool) -> int:
    if target == "all" and remove:
        return _uninstall_all()
    if target == "badge" and remove:
        from . import service
        from .install_badge import BadgeInstallError, uninstall_badge
        try:
            with service.paused():
                removed = uninstall_badge(None)
        except BadgeInstallError as e:
            print(str(e), file=sys.stderr)
            return 1
        print("Pitwall app and keys removed from the badge." if removed else "The badge had no Pitwall app.")
        return 0
    if target == "claude-code":
        path = default_settings_path()
        try:
            r = uninstall(path) if remove else install(path, hook_command())
        except SettingsError as e:
            print(f"pitwall: {e}", file=sys.stderr)
            return 1
        verb = "removed from" if remove else "installed in"
        if r.changed:
            print(f"pitwall hooks {verb} {path}" + (f" (backup: {r.backup.name})" if r.backup else ""))
        else:
            print(f"Nothing to change in {path}")
        if not remove:
            print("New Claude Code sessions report to pitwall right away; open ones on their next prompt "
                  "(or after a restart).")
        return 0
    if target == "badge" and not remove:
        from . import service
        from .install_badge import BadgeInstallError, install_badge
        try:
            with service.paused():  # frees the badge's USB port if the service holds it
                install_badge(None)
        except BadgeInstallError as e:
            print(str(e), file=sys.stderr)
            return 1
        return 0
    return 2  # unreachable: argparse limits the targets


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pitwall", description="A pit wall for your coding agents.")
    ap.add_argument("--version", action="version", version=f"pitwall {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the helper in the foreground")
    s.add_argument("-v", "--verbose", action="store_true")
    s.add_argument("--device", action="append", default=[], metavar="NAME[:usb,ble]",
                   help="hardware to connect (repeatable; overrides the config). Available: badger2350")
    s.add_argument("--config", type=Path, default=None, help="config file (default ~/.pitwall/config.toml)")
    s.add_argument("--log-file", type=Path, default=None, help="log to this file (rotated at 1 MB)")
    st = sub.add_parser("setup", help="detect hardware, agents and terminal; install everything")
    st.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    sv = sub.add_parser("service", help="the background LaunchAgent")
    sv.add_argument("action", choices=["install", "uninstall", "status", "restart"])
    sub.add_parser("status", help="print the current board")
    sub.add_parser("sim", help="a simulated device in this terminal")
    for name, help_ in (("install", "install hooks or the badge app"), ("uninstall", "remove hooks, the badge app, or everything")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("target", choices=["claude-code", "badge"] if name == "install" else ["claude-code", "badge", "all"])
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                            format="%(asctime)s %(name)s: %(message)s",
                            handlers=[log_handler(args.log_file)] if args.log_file else None)
        from .config import ConfigError
        from .server import AlreadyRunning, serve
        try:
            cfg = resolve_config(args.device, args.config)
        except ConfigError as e:
            print(f"pitwall: {e}", file=sys.stderr)
            return 2
        try:
            asyncio.run(serve(cfg=cfg))
        except AlreadyRunning as e:
            print(str(e), file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            pass
        return 0
    if args.cmd == "setup":
        from .setup import run_setup
        return run_setup(yes=args.yes)
    if args.cmd == "service":
        return _cmd_service(args.action)
    if args.cmd == "status":
        return asyncio.run(status_async())
    if args.cmd == "sim":
        from .sim import run_sim
        return asyncio.run(run_sim())
    return _cmd_install(args.target, remove=args.cmd == "uninstall")


if __name__ == "__main__":
    sys.exit(main())
