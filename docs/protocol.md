# pitwall protocol, v1

This is the contract every pitwall plug-in builds against. A device bridge (Stream Deck, macro keypad, a web page…) or another agent's hook can be written from this page alone, in any language.

## Framing

- One **JSON object per line**, UTF-8, terminated by `\n`.
- Every message carries `"v": 1`. Lines with another version are ignored.
- **Skip what you can't parse.** Blank lines, non-JSON, JSON that isn't an object, and wrong versions are dropped without error. The first line after a USB connect is often garbled; the next full `board` fixes everything.
- Every `board` is a **full snapshot**, so devices hold no state between messages.

## States

| Wire value | Name | Meaning |
|---|---|---|
| `green` | 🟢 Green flag | agent is working |
| `box` | 🟡 Box box | agent needs you (permission prompt or question) |
| `done` | 🏁 Chequered flag | agent finished its turn and is waiting for your next prompt |
| `red` | 🔴 Red flag | agent turn failed |

Sort order on every board: `box` (longest wait first), `red`, `done`, `green`; ties by label.

## Where to connect

| Who | How |
|---|---|
| Agent hooks → helper | Unix socket `~/.pitwall/pitwall.sock`: connect, write one `session` line, close |
| Device bridges ↔ helper | Unix socket `~/.pitwall/devices.sock`: a persistent connection, lines both ways |
| Badge ↔ helper | USB serial (115200), or Bluetooth LE (see below) |

`~/.pitwall` can be moved with the `PITWALL_HOME` environment variable.

## Agent → helper

### `session`
```json
{"v":1,"type":"session","agent":"claude-code","id":"5f0c…","state":"box",
 "label":"api","cwd":"/Users/me/work/api",
 "terminal":{"kind":"iterm2","ref":"6F1C2A4E-…"}}
```
- `state` is one of the four states, or `"end"` to remove the session.
- The board labels a session by the last folder of `cwd`. `label` is used only when `cwd` is empty, for agents that have no working folder.
- `terminal` is `null` when the hook can't tell which tab it's in. The session is still shown, but it can't be focused.
- **Never send prompt text, code or tool input.** The helper only needs these fields.

## Device → helper

### `hello` (send first)
```json
{"v":1,"type":"hello","device":"badger2350","uid":"0123abcd4567…","transport":"usb",
 "caps":{"display":[320,240],"color":true,"buttons":["up","down","left","right","select"],"keys":0,"led":true}}
```
- `uid` is stable per physical device. If the same `uid` connects over several transports, the helper uses only the best one (`usb` > `ble` > `socket`): the others get **no boards** and their button messages are ignored, so they show as disconnected until the better link goes away.
- `caps` tells the helper what the device can do. `keys` > 0 means one session per key (e.g. a Stream Deck).

### `focus`
```json
{"v":1,"type":"focus","id":"5f0c…"}
```
Brings that session's terminal tab to the front. Unknown or unfocusable ids are ignored.

### `focus_next_waiting`
```json
{"v":1,"type":"focus_next_waiting"}
```
Focuses the `box` session that has waited longest.

### `ping`
```json
{"v":1,"type":"ping"}
```
Optional keep-alive. The helper ignores it.

## Helper → device

### `hello`
```json
{"v":1,"type":"hello","device":"helper"}
```

### `board`
```json
{"v":1,"type":"board",
 "sessions":[{"id":"5f0c…","label":"api","title":"Fix login redirect","state":"box","age_s":192,"focusable":true},
             {"id":"9a1e…","label":"web","title":null,"state":"green","age_s":12,"focusable":true}],
 "counts":{"box":1,"red":0,"done":0,"green":1}}
```
- Sent right after `hello`, on every change, and **every 5 s as a heartbeat**.
- A device that has had no `board` for **15 s** should show itself as disconnected (keep the last board, dimmed).
- `age_s` is the number of seconds since the session's state last changed.
- `label` is the session's folder name; two sessions in the same folder become `api`, `api·2`.
- `title` is the terminal tab's title (e.g. the topic Claude Code shows in the tab), or `null` when unknown. Show both when they differ.

### `alert`
```json
{"v":1,"type":"alert","id":"5f0c…"}
```
A session just entered `box`. Get the person's attention (flash, LED). It's never sent for other states.

## Bluetooth LE

| | UUID |
|---|---|
| Service | `6f1c0001-9b2a-4c55-8f3e-70697477616c` |
| RX (helper → device), write with response | `6f1c0002-9b2a-4c55-8f3e-70697477616c` |
| TX (device → helper), notify | `6f1c0003-9b2a-4c55-8f3e-70697477616c` |

- Lines are split into chunks of at most *MTU − 3* bytes and reassembled on `\n`.
- **Nothing but pairing traffic flows before a link is authenticated** (next section).

### Pairing and authentication (BLE only)

The badge advertises as `pitwall-<first 8 hex chars of its uid>` with the service UUID above.

**Pairing happens over USB, automatically.** Each time the device says `hello` on a USB link, the helper sends it this Mac's key:
`{"v":1,"type":"pair_key","host":"<host id>","key":"<hex, 32 random bytes>"}`
The device stores it and replies `{"v":1,"type":"paired","host":"<host id>"}`. The key is random, never derived from anything typed, and only ever travels over the cable.

**Every BLE connection then authenticates both ways:**
1. The helper connects, subscribes to TX and sends its `hello`. The device answers with its `hello`, then a `challenge` with a fresh random device nonce `dn`:
   `{"v":1,"type":"challenge","nonce":"<hex 16 bytes>"}`
2. The helper picks its own fresh nonce `hn` and sends
   `{"v":1,"type":"auth","host":"<host id>","hn":"<hex 16 bytes>","mac":"<hex HMAC-SHA256(key, "auth" ‖ dn ‖ hn)>"}`.
3. If it matches, the device replies `{"v":1,"type":"auth_ok","mac":"<hex HMAC-SHA256(key, "dev" ‖ hn ‖ dn)>"}`, which proves it knows the key too. Otherwise it replies `auth_fail`. A challenge can be answered only once, whether the answer is right or wrong. The helper attaches the link only after checking the device's mac.
4. Both sides use a per-connection key `skey = HMAC-SHA256(key, "sess" ‖ dn ‖ hn)` and nonce `dn ‖ hn` for sealing.
5. Once authenticated, every line in both directions is sent **sealed**:
   `{"v":1,"type":"sealed","n":<counter>,"d":"<base64 ciphertext>","t":"<hex 16-byte tag>"}`.
   - The plaintext is the original line, without the `\n`.
   - Ciphertext = plaintext XOR keystream, where the keystream is SHA-256(`skey ‖ dir ‖ nonce ‖ n ‖ block-index`) concatenated block by block. `dir` is `"h2d"` or `"d2h"`. `n` counts up from 0 per direction, and a receiver drops any `n` that isn't larger than the last one.

**Byte encodings** (reference: `src/pitwall/seal.py`, which runs unchanged on the badge):
- `dir`, `"auth"`, `"dev"`, `"sess"` are ASCII bytes; `dn` and `hn` are 16 raw bytes each, so the sealing nonce `dn ‖ hn` is 32 bytes.
- `n` is an 8-byte big-endian integer; the block index is a 4-byte big-endian integer starting at 0.
- Hex fields are lowercase; `d` is standard base64 (with padding).
- This is a small home-made construction (SHA-256 in counter mode, encrypt-then-MAC with HMAC-SHA256 truncated to 16 bytes) chosen because the badge has `hashlib` but no AEAD. It keeps session names unreadable to nearby sniffers and stops strangers pressing buttons; it hasn't had a formal review.
   - `t` = the first 16 bytes of HMAC-SHA256(`skey`, `dir ‖ n ‖ ciphertext`). Lines with a bad tag are dropped.

USB and the local socket aren't sealed: they don't leave the machine.
