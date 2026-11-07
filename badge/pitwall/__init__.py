# pitwall: a pit wall for your coding agents, on the GitHub Universe badge.
# Shows every agent session's state and focuses its terminal tab on a button press.
import math

import links
import model

badge.mode(HIRES | VSYNC)

try:
    import missing_details
    FONT = missing_details.mona_sans()
except Exception:
    FONT = None

UID = badge.uid if isinstance(badge.uid, str) else "".join("%02x" % b for b in badge.uid)
CAPS = {"display": [320, 240], "color": True,
        "buttons": ["up", "down", "left", "right", "select"], "keys": 0, "led": True}

bg = color.rgb(12, 14, 20)
panel = color.rgb(30, 34, 46)
white = color.rgb(238, 240, 246)
dim = color.rgb(238, 240, 246, 110)
faint = color.rgb(238, 240, 246, 50)
sub = color.rgb(238, 240, 246, 165)
amber = color.rgb(255, 196, 40)
red = color.rgb(240, 70, 70)
green = color.rgb(80, 210, 110)
black = color.rgb(20, 20, 20)

STATE_PEN = {"box": amber, "red": red, "green": green}
STATE_WORD = {"red": "failed", "done": "done", "green": "working"}

ROW_TOP, ROW_H, ROWS = 27, 31, 6
FOOT_Y = 215

def hello(transport):
    return {"type": "hello", "device": "badger2350", "uid": UID, "transport": transport, "caps": CAPS}


view = model.View()
usb = links.Usb()
try:
    ble = links.Ble(UID, hello("ble"))
except Exception as e:
    print("pitwall: bluetooth unavailable", e)
    ble = None

last_rx = {"usb": None, "ble": None}
last_hello_ms = -10000
restarting_until = 0


def active_transport(now):
    try:
        plugged = badge.usb_connected()
    except Exception:
        plugged = True
    return model.pick_transport(now, last_rx["usb"], plugged, ble is not None and ble.authed)


def send(msg, now):
    t = active_transport(now)
    if t == "usb":
        usb.send(msg)
    elif t == "ble":
        ble.send(msg)


def handle(msg, transport, now):
    kind = msg.get("type")
    if kind == "hello":
        if transport == "usb":
            usb.send(hello("usb"))
        return
    if kind == "pair_key" and transport == "usb":
        # USB is a local cable: the helper hands over its Bluetooth key here
        try:
            host, key = msg["host"], bytes.fromhex(msg["key"])
        except Exception:
            return
        if len(key) == 32:
            if ble is not None:
                ble.add_key(host, key)
            else:
                keys = links.load_keys()
                keys[host] = key
                links.save_keys(keys)
            usb.send({"type": "paired", "host": host})
        return
    if kind in ("board", "alert"):
        last_rx[transport] = now
        # while USB is live, ignore a stale BLE board (the helper only talks on one anyway)
        if transport == "ble" and active_transport(now) == "usb":
            return
        view.on_message(msg, now)


def text(s, x, y, size, pen):
    screen.pen = pen
    screen.text(s, x, y, size)


def text_w(s, size):
    return screen.measure_text(s, size)[0]


def chip(state, x, y, s, flash):
    if state == "done":
        half = s / 2
        for i in range(2):
            for j in range(2):
                screen.pen = white if (i + j) % 2 == 0 else black
                screen.shape(shape.rectangle(x + i * half, y + j * half, half, half))
        return
    pen = STATE_PEN.get(state, dim)
    if state == "box" and flash:
        pen = white
    screen.pen = pen
    screen.shape(shape.rounded_rectangle(x, y, s, s, 3))


def draw_header(now):
    screen.pen = panel
    screen.shape(shape.rectangle(0, 0, 320, 24))
    x = 8
    for state in ("box", "red", "done", "green"):
        chip(state, x, 6, 12, False)
        n = str(view.counts.get(state, 0))
        text(n, x + 16, 4, 14, white)
        x += 26 + text_w(n, 14)
    t = active_transport(now)
    link = "USB" if t == "usb" else ("BT" if t == "ble" else "--")
    try:
        level = int(badge.battery_level())
    except Exception:
        level = None
    right = link + ("  %d%%" % level if level is not None else "")
    if len(view.sessions) > ROWS:
        right = "%d/%d   " % (view.cursor + 1, len(view.sessions)) + right
    text(right, 312 - text_w(right, 12), 6, 12, dim if t else red)


def fit(s, size, max_w):
    """Cut text to fit max_w pixels, with an ellipsis."""
    s = str(s)
    if text_w(s, size) <= max_w:
        return s
    while s and text_w(s + "…", size) > max_w:
        s = s[:-1]
    return s + "…"


def draw_rows(now, stale):
    rows = view.rows(ROWS)
    if not rows:
        msg = "No agent sessions yet" if not stale else "Waiting for the pitwall helper…"
        text(msg, 160 - text_w(msg, 16) / 2, 105, 16, dim)
        return
    flash = view.alerting(now) and (now // 250) % 2 == 0
    for idx, (i, s, selected) in enumerate(rows):
        y = ROW_TOP + idx * ROW_H
        if selected:
            screen.pen = panel
            screen.shape(shape.rounded_rectangle(4, y, 312, ROW_H - 2, 6))
        state = s.get("state", "")
        chip(state, 12, y + 8, 13, flash and s.get("id") == view.alert_id)
        if state == "box":
            right, rpen = model.fmt_age(s.get("age_s", 0)), amber
        else:
            right, rpen = STATE_WORD.get(state, ""), dim
        rw = text_w(right, 12)
        text(right, 308 - rw, y + 9, 12, rpen if not stale else faint)
        max_w = 308 - rw - 10 - 34
        live = s.get("focusable", True) and not stale
        title, folder = s.get("title"), str(s.get("label", ""))
        if title and title.strip().lower() != folder.strip().lower():
            text(fit(title, 14, max_w), 34, y + 2, 14, white if live else dim)
            text(fit(folder, 11, max_w), 34, y + 17, 11, sub if live else faint)
        else:
            text(fit(title or folder, 14, max_w), 34, y + 8, 14, white if live else dim)


def draw_footer(stale, now):
    screen.pen = red if stale else panel
    screen.shape(shape.rectangle(0, FOOT_Y + 2, 320, 240 - FOOT_Y - 2))
    if now < restarting_until:
        msg = "Restarting Bluetooth…"
        text(msg, 160 - text_w(msg, 12) / 2, FOOT_Y + 5, 12, white)
        return
    if stale:
        x = 8
        text("No connection", x, FOOT_Y + 5, 12, white)
        if ble is not None:
            x = 320 - 8 - text_w("SELECT restart Bluetooth", 12)
            text("SELECT", x, FOOT_Y + 5, 12, amber)
            text("restart Bluetooth", x + text_w("SELECT ", 12), FOOT_Y + 5, 12, white)
        return
    x = 8
    for key, what in (("SELECT", "focus"), ("RIGHT", "next box box"), ("LEFT", "top")):
        text(key, x, FOOT_Y + 5, 12, amber)
        x += text_w(key, 12) + 4
        text(what, x, FOOT_Y + 5, 12, white)
        x += text_w(what, 12) + 12


def update():
    global last_hello_ms, restarting_until
    now = badge.ticks
    for m in usb.read():
        handle(m, "usb", now)
    if ble is not None:
        for m in ble.read():
            handle(m, "ble", now)
        ble.keep_advertising()

    if badge.pressed(BUTTON_UP):
        view.move(-1)
    elif badge.pressed(BUTTON_DOWN):
        view.move(1)
    elif badge.pressed(BUTTON_LEFT):
        view.move(-len(view.sessions))
    elif badge.pressed(BUTTON_SELECT):
        action = model.select_action(view.stale(now), view.selected_id(), ble is not None)
        if action == "focus":
            send({"type": "focus", "id": view.selected_id()}, now)
        elif action == "restart_ble":
            restarting_until = now + 2000
            try:
                ble.restart()
            except Exception as e:
                print("pitwall: bluetooth restart failed", e)
    elif badge.pressed(BUTTON_RIGHT):
        send({"type": "focus_next_waiting"}, now)

    stale = view.stale(now)
    if stale and now - last_hello_ms > 5000:
        usb.send(hello("usb"))  # the helper may have missed our first hello
        last_hello_ms = now

    try:
        badge.caselights((0.5 + 0.5 * math.sin(now / 120)) if view.alerting(now) else 0)
    except Exception:
        pass

    if FONT is not None:
        screen.font = FONT
    screen.pen = bg
    screen.clear()
    draw_header(now)
    draw_rows(now, stale)
    draw_footer(stale, now)


run(update)
