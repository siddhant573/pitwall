---
name: pitwall
description: Set up, check and troubleshoot pitwall, the desk device that shows every coding-agent session's state (Green flag / Box box / Chequered flag / Red flag) and jumps to its iTerm2 tab. Use when the user asks to install pitwall, connect the GitHub Universe badge (badger2350), check why a session isn't showing or a tab isn't switching, or stop/remove pitwall.
---

# pitwall

pitwall has three parts: Claude Code **hooks** (`pitwall-hook`) report each session's state; the **helper** (`pitwall serve`, normally a LaunchAgent) keeps the board; **devices** (the `badger2350` badge over USB or Bluetooth) show it and send "focus this tab" back.

## Set up

```bash
pipx install pitwall-agents        # or: pipx install git+https://github.com/siddhant573/pitwall
pitwall setup                      # detects badge / agents / terminal, asks once, installs everything
```

`pitwall setup --yes` skips the question. It writes `~/.pitwall/config.toml`, adds hooks to `~/.claude/settings.json` (with a backup), installs the badge app if the badge is plugged in, and starts the LaunchAgent. Tell the user to open **Pitwall** from the badge's home menu and to allow the macOS prompts for Bluetooth and for controlling iTerm2.

## Check

| Question | Command |
|---|---|
| Is the helper running? | `pitwall service status` |
| What does the board show? | `pitwall status` |
| What is configured? | `cat ~/.pitwall/config.toml` |
| What happened recently? | `tail -50 ~/.pitwall/serve.log` |

Run the helper in the foreground with logs for debugging: `pitwall service uninstall && pitwall serve -v` (reinstall afterwards with `pitwall service install`).

## Troubleshoot

- **A session doesn't appear:** new sessions show up right away; already-open ones on their next prompt (or after a restart). Check `pitwall-hook` is in `~/.claude/settings.json` hooks; if not, `pitwall install claude-code`.
- **Pressing SELECT doesn't switch tabs:** the log says "couldn't switch to …'s tab" when macOS hasn't allowed controlling iTerm2: System Settings → Privacy & Security → Automation (after "Don't allow": `tccutil reset AppleEvents`). A closed tab is dropped from the board automatically.
- **Badge says "No connection":** press **SELECT** on the badge to restart its Bluetooth. If that doesn't help, the helper isn't running or the badge isn't paired: `pitwall service status`, and plug the badge in over USB once (pairing for Bluetooth happens over the cable automatically).
- **Bluetooth doesn't take over when unplugged:** the log should show `badge … connected over Bluetooth` within a few seconds. The badge must have been plugged in once with Pitwall open (that pairs it). If the log says the scan failed, allow Bluetooth for the helper in Privacy & Security → Bluetooth.
- **`pitwall install badge` can't find the drive:** double-tap the badge's reset button to enter disk mode, then run it again.

## Choose hardware

`serve` uses the devices in the config; `--device` overrides it for one run:

```bash
pitwall serve --device badger2350          # USB and Bluetooth
pitwall serve --device badger2350:usb      # USB only
```

## Remove

```bash
pitwall uninstall all          # service, hooks, badge app + keys, ~/.pitwall
pipx uninstall pitwall-agents
```

## Rules

- Never edit `~/.claude/settings.json` by hand to add pitwall; use `pitwall install claude-code`.
- Devices only show status and switch tabs. Don't add anything that approves or answers prompts from a device.
