import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "badge" / "pitwall"))
import model  # noqa: E402


def line(msg):
    return (json.dumps(dict(msg, v=1), ensure_ascii=False) + "\n").encode()


def board(n, box=()):
    sessions = [{"id": f"s{i}", "label": f"proj{i}", "state": "box" if i in box else "green",
                 "age_s": i, "focusable": True} for i in range(n)]
    return {"type": "board", "sessions": sessions, "counts": {"box": len(box), "red": 0, "done": 0,
                                                               "green": n - len(box)}}


def test_decoder_skip_partial_utf8():
    d = model.Decoder()
    data = b"\x00junk\n" + line({"type": "x"})[:5]
    assert d.feed(data) == []
    rest = line({"type": "x"})[5:] + b'{"v":2}\n' + line({"type": "board", "label": "café-🏎️"})
    out = []
    for i in range(0, len(rest), 3):
        out += d.feed(rest[i:i + 3])
    assert [m["type"] for m in out] == ["x", "board"] and out[1]["label"] == "café-🏎️"


def test_cursor_stays_visible_with_20_sessions():
    v = model.View()
    v.on_message(board(20), 0)
    for _ in range(12):
        v.move(1)
    rows = v.rows(8)
    assert len(rows) == 8
    assert any(sel for _, _, sel in rows)
    assert v.selected_id() == "s12"
    v.move(-100)
    assert v.selected_id() == "s0" and v.rows(8)[0][0] == 0


def test_cursor_follows_session_across_boards():
    v = model.View()
    v.on_message(board(5), 0)
    v.move(3)
    assert v.selected_id() == "s3"
    b = board(5)
    b["sessions"] = [b["sessions"][3]] + [s for s in b["sessions"] if s["id"] != "s3"]
    v.on_message(b, 10)
    assert v.selected_id() == "s3" and v.cursor == 0
    v.move(4)                    # cursor index 4 (s4)
    v.on_message(board(2), 20)   # s4 gone → clamp to the last row
    assert v.selected_id() == "s1"
    v.on_message(board(0), 30)
    assert v.selected_id() is None and v.rows(8) == []


def test_fmt_age():
    assert model.fmt_age(180) == "3m" and model.fmt_age(3900) == "1h05" and model.fmt_age(12) == "12s"


def test_stale_after_15s():
    v = model.View()
    assert v.stale(0) is True
    v.on_message(board(1), 1000)
    assert v.stale(16000) is False
    assert v.stale(16001) is True


def test_alerting_window_3s():
    v = model.View()
    v.on_message({"type": "alert", "id": "s1"}, 5000)
    assert v.alerting(5000) and v.alerting(7999) and not v.alerting(8000)


def test_pick_transport():
    pick = model.pick_transport
    # plugged in and the helper is talking over USB
    assert pick(now=20000, usb_last=19000, usb_plugged=True, ble_authed=True) == "usb"
    # unplugged: switch to Bluetooth immediately, no 15 s wait
    assert pick(now=20000, usb_last=19000, usb_plugged=False, ble_authed=True) == "ble"
    # plugged in but nothing on USB for a while (e.g. charger, helper not running)
    assert pick(now=40000, usb_last=19000, usb_plugged=True, ble_authed=True) == "ble"
    # nothing usable
    assert pick(now=20000, usb_last=None, usb_plugged=False, ble_authed=False) is None
    assert pick(now=20000, usb_last=19000, usb_plugged=False, ble_authed=False) is None


def test_readvertise_due():
    due = model.readvertise_due
    assert due(connected=False, since_adv_ms=None) is True
    assert due(connected=False, since_adv_ms=5000) is False
    assert due(connected=False, since_adv_ms=10001) is True
    assert due(connected=True, since_adv_ms=99999) is False


def test_select_action():
    act = model.select_action
    assert act(stale=True, selected="s1", ble_available=True) == "restart_ble"
    assert act(stale=True, selected=None, ble_available=True) == "restart_ble"
    assert act(stale=False, selected="s1", ble_available=True) == "focus"
    assert act(stale=False, selected=None, ble_available=True) is None
    assert act(stale=True, selected="s1", ble_available=False) is None
