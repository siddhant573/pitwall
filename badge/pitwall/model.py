# pitwall badge: pure state (no hardware). Runs on MicroPython and CPython (tests).
import json

STALE_MS = 15000
ALERT_MS = 3000


class Decoder:
    """Bytes in, protocol messages out. Skips anything that isn't a v1 JSON object."""

    def __init__(self):
        self.buf = b""

    def feed(self, data):
        self.buf += data
        out = []
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except Exception:
                continue
            if isinstance(msg, dict) and msg.get("v") == 1:
                out.append(msg)
        if len(self.buf) > 16384:
            self.buf = b""
        return out


def fmt_age(s):
    s = max(0, int(s))
    if s < 60:
        return "%ds" % s
    if s < 3600:
        return "%dm" % (s // 60)
    return "%dh%02d" % (s // 3600, (s % 3600) // 60)


class View:
    def __init__(self):
        self.sessions = []
        self.counts = {"box": 0, "red": 0, "done": 0, "green": 0}
        self.cursor = 0
        self.top = 0
        self.last_board_ms = None
        self.alert_ms = None
        self.alert_id = None

    def on_message(self, msg, now_ms):
        kind = msg.get("type")
        if kind == "board":
            keep = self.selected_id()
            self.sessions = msg.get("sessions") or []
            self.counts = msg.get("counts") or self.counts
            self.last_board_ms = now_ms
            ids = [s.get("id") for s in self.sessions]
            if keep in ids:
                self.cursor = ids.index(keep)
            self._clamp()
        elif kind == "alert":
            self.alert_ms = now_ms
            self.alert_id = msg.get("id")

    def _clamp(self):
        n = len(self.sessions)
        self.cursor = 0 if n == 0 else max(0, min(self.cursor, n - 1))

    def move(self, delta):
        self.cursor += delta
        self._clamp()

    def selected_id(self):
        if not self.sessions:
            return None
        return self.sessions[self.cursor].get("id")

    def rows(self, max_rows=8):
        n = len(self.sessions)
        if n == 0:
            return []
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + max_rows:
            self.top = self.cursor - max_rows + 1
        self.top = max(0, min(self.top, max(0, n - max_rows)))
        out = []
        for i in range(self.top, min(n, self.top + max_rows)):
            out.append((i, self.sessions[i], i == self.cursor))
        return out

    def stale(self, now_ms):
        return self.last_board_ms is None or now_ms - self.last_board_ms > STALE_MS

    def alerting(self, now_ms):
        return self.alert_ms is not None and now_ms - self.alert_ms < ALERT_MS


READVERTISE_MS = 10000


def pick_transport(now, usb_last, usb_plugged, ble_authed):
    """Which link the badge uses. USB while the helper is talking on it; Bluetooth the moment the cable is out."""
    if usb_plugged and usb_last is not None and now - usb_last <= STALE_MS:
        return "usb"
    if ble_authed:
        return "ble"
    return None


def readvertise_due(connected, since_adv_ms):
    """Safety net: re-start Bluetooth advertising every 10 s while nobody is connected."""
    return not connected and (since_adv_ms is None or since_adv_ms > READVERTISE_MS)


def select_action(stale, selected, ble_available):
    """What SELECT does: focus the selected tab, or, while disconnected, restart Bluetooth."""
    if stale:
        return "restart_ble" if ble_available else None
    return "focus" if selected else None
