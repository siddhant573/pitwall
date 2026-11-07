"""`pitwall setup`: find the hardware, agents and terminal, write the config, install everything."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config as cfgmod

_ITERM_APPS = (Path("/Applications/iTerm.app"), Path.home() / "Applications" / "iTerm.app")
_OTHER_TERMINALS = {"Apple_Terminal": "Terminal.app", "ghostty": "Ghostty", "WezTerm": "WezTerm",
                    "vscode": "VS Code", "WarpTerminal": "Warp", "tmux": "tmux"}


@dataclass
class Env:
    list_badges: Callable[[], list[str]]
    which: Callable[[str], str | None] = shutil.which
    exists: Callable[[Path], bool] = lambda p: Path(p).exists()
    term_program: str | None = None


@dataclass
class Detected:
    devices: dict[str, str] = field(default_factory=dict)   # name -> how it was found
    agents: list[str] = field(default_factory=list)
    terminal: str | None = None
    unsupported_terminal: str | None = None


@dataclass
class Steps:
    install_agent: Callable[[str], None]
    install_badge: Callable[[], None]
    install_service: Callable[[], None]


def default_env() -> Env:
    from .links.usb import find_badge_ports
    return Env(list_badges=find_badge_ports, term_program=os.environ.get("TERM_PROGRAM"))


def detect(env: Env) -> Detected:
    d = Detected()
    ports = env.list_badges()
    if ports:
        d.devices["badger2350"] = f"connected over USB ({ports[0]})"
    if env.which("claude") or env.exists(Path.home() / ".claude"):
        d.agents.append("claude-code")
    if any(env.exists(p) for p in _ITERM_APPS) or env.term_program == "iTerm.app":
        d.terminal = "iterm2"
    elif env.term_program:
        d.unsupported_terminal = _OTHER_TERMINALS.get(env.term_program, env.term_program)
    return d


def run_setup(yes: bool = False, env: Env | None = None, steps: Steps | None = None,
              config_file: Path | None = None, out=print, ask=input) -> int:
    env = env or default_env()
    d = detect(env)
    out("pitwall setup\n")
    out("  Hardware:  " + (", ".join(f"{n} ({how})" for n, how in d.devices.items())
                          or "no badge found over USB (you can plug it in later)"))
    out("  Agents:    " + (", ".join(d.agents) or "none found"))
    out("  Terminal:  " + (d.terminal or f"{d.unsupported_terminal or 'none'} (not supported yet)"))
    out("")
    if d.terminal is None:
        out("pitwall needs iTerm2 to switch tabs (more terminals are on the roadmap). "
            "Install iTerm2 and run `pitwall setup` again.")
        return 1
    if not d.agents:
        out("No supported agent found. Install Claude Code and run `pitwall setup` again.")
        return 1

    cfg = cfgmod.Config(devices={"badger2350": list(cfgmod.DEVICES["badger2350"])},
                        agents=d.agents, terminal=d.terminal)
    plan = [f"write {config_file or cfgmod.config_path()}",
            "add pitwall's hooks to " + ", ".join(cfg.agents)]
    if d.devices:
        plan.append("install the Pitwall app on the badge (it restarts once)")
    plan.append("keep `pitwall serve` running with a LaunchAgent (starts at login)")
    out("This will:")
    for i, step in enumerate(plan, 1):
        out(f"  {i}. {step}")
    if not yes and ask("\nGo ahead? [Y/n] ").strip().lower() not in ("", "y", "yes"):
        out("Nothing changed.")
        return 1

    from .agents.claude_settings import SettingsError
    from .install_badge import BadgeInstallError
    steps = steps or default_steps()
    path = cfgmod.save(cfg, config_file)
    out(f"\n✓ config written to {path}")
    todo = []
    for a in cfg.agents:
        try:
            steps.install_agent(a)
            out(f"✓ {a} hooks installed")
        except SettingsError as e:
            out(f"! {a} hooks: {e}")
            todo.append(f"fix that, then run `pitwall install {a}`")
    badge_ok = False
    if d.devices:
        try:
            steps.install_badge()
            badge_ok = True
            out("✓ badge app installed")
        except BadgeInstallError as e:
            out(f"! badge: {e}")
            todo.append("run `pitwall install badge`")
    else:
        todo.append("plug the badge in over USB and run `pitwall install badge`")
    steps.install_service()
    out("✓ pitwall is running in the background and starts at login")
    if badge_ok:
        out("\nOpen Pitwall from the badge's home menu and keep it plugged in until the header shows USB:"
            " that pairs it for Bluetooth.")
    out("macOS may ask once to let pitwall use Bluetooth and control iTerm2: allow both.")
    if todo:
        out("\nStill to do:")
        for t in todo:
            out(f"  • {t}")
        return 1 if any(t.startswith("fix") or t.startswith("run") for t in todo) else 0
    return 0


def default_steps() -> Steps:
    from . import service
    from .agents.claude_settings import default_settings_path, hook_command, install
    from .install_badge import install_badge

    def agent(name: str) -> None:
        if name == "claude-code":
            install(default_settings_path(), hook_command())

    def badge() -> None:
        with service.paused():
            install_badge(None)

    return Steps(install_agent=agent, install_badge=badge, install_service=service.install)
