# Changelog

## 0.1.3 (first public release)

- Claude Code hooks report every session: 🟢 Green flag, 🟡 Box box, 🏁 Chequered flag, 🔴 Red flag
- GitHub Universe 2026 badge (`badger2350`) shows the board over USB or Bluetooth; SELECT / RIGHT jump to the session's iTerm2 tab; SELECT restarts Bluetooth while disconnected
- Rows show the iTerm2 tab title with the folder
- `pitwall setup` detects the badge, agents and terminal, writes `~/.pitwall/config.toml`, installs the hooks and the badge app, and runs the helper as a LaunchAgent
- Bluetooth pairs automatically over the USB cable (random 256-bit key, mutual auth per connection)
- `pitwall uninstall all` removes everything
- Open JSON-lines protocol for new devices, and two Claude Code skills
