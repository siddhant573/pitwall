# Contributing

Thanks for helping. pitwall is small on purpose; the most useful contributions are new devices, agents and terminals.

## Develop

```bash
git clone https://github.com/siddhant573/pitwall && cd pitwall
uv run --extra dev pytest -q          # the whole suite, no hardware needed
uv run pitwall sim                    # a device in your terminal (start `uv run pitwall serve -v` first)
```

Write the failing test first; every change comes with one. Hardware-free fakes live in `tests/` (fake links, a fake badge built on the real `seal.py`).

## Where things go

| Adding | Touch |
|---|---|
| A device that talks to the socket (Stream Deck, keypad, web page…) | nothing in pitwall: build a bridge against [docs/protocol.md](docs/protocol.md) (the `pitwall-device` skill walks through it) |
| A device pitwall connects to itself | `DEVICES` in `src/pitwall/config.py`, a watcher in `server.watchers_for`, a link in `src/pitwall/links/` |
| An agent | a mapping in `src/pitwall/agents/` (see `claude_code.py`) and its installer |
| A terminal | `src/pitwall/terminals/` (`focus` and `titles`, see `iterm2.py`) |

## Rules

- Devices only show status and switch tabs. Nothing that approves, answers or sends prompts.
- The hook stays stdlib-only, fast and silent, and never fails the agent.
- Nothing from prompts, code or tool input leaves the hook.
- The badge code in `badge/pitwall/` must stay MicroPython-compatible; `src/pitwall/seal.py` runs on both sides unchanged.

## Releasing (maintainer)

Bump `__version__` in `src/pitwall/__init__.py`, add a CHANGELOG entry, then `git tag vX.Y.Z && git push --tags`. CI tests, publishes to PyPI and creates the GitHub release.
