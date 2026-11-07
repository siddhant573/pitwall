"""pitwall configuration: which devices, agents and terminal to use. Lives in ~/.pitwall/config.toml."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from . import paths

# What this version supports. Add new hardware, agents and terminals here.
DEVICES = {"badger2350": ("usb", "ble")}          # GitHub Universe 2026 badge (Pimoroni Badger 2350)
AGENTS = ("claude-code",)
TERMINALS = ("iterm2",)


class ConfigError(Exception):
    pass


@dataclass
class Config:
    devices: dict[str, list[str]] = field(default_factory=lambda: {"badger2350": ["usb", "ble"]})
    agents: list[str] = field(default_factory=lambda: ["claude-code"])
    terminal: str = "iterm2"


def config_path(home: Path | None = None) -> Path:
    return (home or paths.home_dir()) / "config.toml"


def _check_device(name: str, transports: list[str]) -> None:
    if name not in DEVICES:
        raise ConfigError(f"unknown device '{name}'. Available: {', '.join(DEVICES)}")
    for t in transports:
        if t not in DEVICES[name]:
            raise ConfigError(f"unknown transport '{t}' for {name}. Available: {', '.join(DEVICES[name])}")


def validate(cfg: Config) -> Config:
    if not isinstance(cfg.devices, dict):
        raise ConfigError("devices must be a table, e.g. [devices.badger2350]")
    for name, transports in cfg.devices.items():
        _check_device(name, transports)
    for a in cfg.agents:
        if a not in AGENTS:
            raise ConfigError(f"unknown agent '{a}'. Available: {', '.join(AGENTS)}")
    if cfg.terminal not in TERMINALS:
        raise ConfigError(f"unknown terminal '{cfg.terminal}'. Available: {', '.join(TERMINALS)}")
    return cfg


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} isn't valid TOML: {e}") from e
    default = Config()
    raw_devices = data.get("devices", {name: {"transports": t} for name, t in default.devices.items()})
    if not isinstance(raw_devices, dict):
        raise ConfigError(f"{path}: devices must be a table, e.g. [devices.badger2350]")
    devices = {}
    for name, opts in raw_devices.items():
        transports = (opts or {}).get("transports") if isinstance(opts, dict) else None
        devices[name] = list(transports) if transports else list(DEVICES.get(name, ()))
    return validate(Config(devices=devices,
                           agents=list(data.get("agents", default.agents)),
                           terminal=str(data.get("terminal", default.terminal))))


def dump(cfg: Config) -> str:
    q = lambda xs: "[" + ", ".join(f'"{x}"' for x in xs) + "]"
    lines = ["# pitwall configuration. `pitwall setup` writes this; edit freely.", "",
             f'terminal = "{cfg.terminal}"', f"agents = {q(cfg.agents)}", ""]
    for name, transports in cfg.devices.items():
        lines += [f"[devices.{name}]", f"transports = {q(transports)}", ""]
    return "\n".join(lines)


def save(cfg: Config, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(validate(cfg)))
    return path


def parse_device_args(args: list[str]) -> dict[str, list[str]]:
    """`badger2350` → all transports; `badger2350:usb` or `badger2350:usb,ble` → just those."""
    out = {}
    for arg in args:
        name, _, rest = arg.partition(":")
        transports = [t for t in rest.split(",") if t] if rest else list(DEVICES.get(name, ()))
        _check_device(name, transports)
        out[name] = transports
    return out
