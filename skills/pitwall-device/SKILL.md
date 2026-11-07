---
name: pitwall-device
description: Build a new pitwall device or bridge (Stream Deck, macro keypad, a web page, another badge) that shows the agent session board and sends focus requests, using pitwall's JSON-lines protocol. Use when the user wants to connect new hardware or a new client to pitwall.
---

# Write a pitwall device

The contract is `docs/protocol.md` in the pitwall repo. Read it first; you don't need the helper's code.

## The shortest working bridge

1. Connect to the Unix socket `~/.pitwall/devices.sock` (or `$PITWALL_HOME/devices.sock`).
2. Send one line: `{"v":1,"type":"hello","device":"<your-device>","uid":"<stable id>","transport":"socket","caps":{...}}`.
3. Read lines. Each `board` is a full snapshot: draw it. `alert` means a session just entered Box box: get attention.
4. On a button press send `{"v":1,"type":"focus","id":"<session id>"}` or `{"v":1,"type":"focus_next_waiting"}`.
5. If no `board` arrives for 15 s, show yourself as disconnected.

`pitwall sim` (src/pitwall/sim.py) is a complete reference device in ~100 lines.

## Rules

- Skip lines you can't parse; never crash on them.
- Use a stable `uid` per physical device, so the helper can prefer the best link when one device connects several ways.
- Show both `title` (the terminal tab title, may be null) and `label` (folder name).
- Sort nothing yourself: the board already comes in order (Box box longest-waiting first, then Red flag, Chequered, Green flag).
- Devices only show status and switch tabs. Don't send anything else.

## Adding it to pitwall itself

A device that pitwall should connect to directly (not a bridge on the socket) goes in `src/pitwall/config.py` (`DEVICES`, name → transports) and gets a watcher in `server.watchers_for`. Add tests with a fake link like `tests/test_usb_link.py`.
