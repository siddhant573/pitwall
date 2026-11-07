import asyncio

from fakes import FakeLink, settle
from pitwall.board import Board
from pitwall.hub import Hub
from fakes import session_event
from pitwall.protocol import hello_device


def mkhub():
    calls = []
    hub = Hub(Board(clock=lambda: 0.0), focus=lambda t: calls.append(t) or "ok")
    return hub, calls


def ev(id, state, ref=None):
    return session_event("claude-code", id, state, id, f"/w/{id}",
                         {"kind": "iterm2", "ref": ref or f"U-{id}"})


def connect(hub, transport, uid="B1"):
    link = FakeLink(transport)
    hub.attach(link)
    hub.on_message(link, hello_device("badger2350", uid, transport, {}) | {"v": 1})
    return link


async def test_hello_gets_hello_and_board():
    hub, _ = mkhub()
    usb = connect(hub, "usb")
    await settle()
    assert usb.types() == ["hello", "board"]


async def test_usb_wins_and_single_focus():
    hub, calls = mkhub()
    hub.apply_session(ev("s1", "box"))
    usb = connect(hub, "usb")
    ble = connect(hub, "ble")
    await settle()
    hub.on_message(ble, {"v": 1, "type": "focus", "id": "s1"})
    hub.on_message(usb, {"v": 1, "type": "focus", "id": "s1"})
    await settle()
    assert calls == [{"kind": "iterm2", "ref": "U-s1"}]
    await hub.broadcast()
    assert usb.types()[-1] == "board"
    assert ble.sent == []
    assert hub.active_links() == [usb]


async def test_ble_first_then_usb_takes_over():
    hub, _ = mkhub()
    ble = connect(hub, "ble")
    await settle()
    usb = connect(hub, "usb")
    await settle()
    n = len(ble.sent)
    await hub.broadcast()
    assert len(ble.sent) == n and usb.types()[-1] == "board"


async def test_usb_unplug_falls_back_to_ble():
    hub, _ = mkhub()
    usb = connect(hub, "usb")
    ble = connect(hub, "ble")
    await settle()
    hub.on_closed(usb)
    await settle()
    assert ble.last()["type"] == "board"
    assert hub.active_links() == [ble]


async def test_different_uids_are_independent_and_missing_uid_unique():
    hub, _ = mkhub()
    a = connect(hub, "usb", uid="A")
    b = connect(hub, "usb", uid="B")
    s1 = FakeLink("socket"); hub.attach(s1); hub.on_message(s1, {"v": 1, "type": "hello", "device": "sim"})
    s2 = FakeLink("socket"); hub.attach(s2); hub.on_message(s2, {"v": 1, "type": "hello", "device": "sim"})
    await settle()
    assert set(map(id, hub.active_links())) == set(map(id, [a, b, s1, s2]))


async def test_alert_sent_on_entering_box_only():
    hub, _ = mkhub()
    usb = connect(hub, "usb")
    await settle()
    hub.apply_session(ev("s1", "green"))
    await settle()
    assert "alert" not in usb.types()
    hub.apply_session(ev("s1", "box"))
    await settle()
    assert usb.types()[-2:] == ["board", "alert"] and usb.last()["id"] == "s1"
    hub.apply_session(ev("s1", "box"))
    await settle()
    assert usb.types().count("alert") == 1


async def test_focus_next_waiting_focuses_longest_box():
    t = [0.0]
    calls = []
    hub = Hub(Board(clock=lambda: t[0]), focus=lambda term: calls.append(term) or "ok")
    hub.apply_session(ev("a", "box"))
    t[0] = 1
    hub.apply_session(ev("b", "box"))
    usb = connect(hub, "usb")
    hub.on_message(usb, {"v": 1, "type": "focus_next_waiting"})
    await settle()
    assert calls == [{"kind": "iterm2", "ref": "U-a"}]


async def test_focus_unknown_or_unfocusable_is_noop():
    hub, calls = mkhub()
    hub.apply_session(session_event("claude-code", "x", "box", "x", "/w/x", None))
    usb = connect(hub, "usb")
    hub.on_message(usb, {"v": 1, "type": "focus", "id": "x"})
    hub.on_message(usb, {"v": 1, "type": "focus", "id": "nope"})
    hub.on_message(usb, {"v": 1, "type": "focus"})
    await settle()
    assert calls == []


async def test_messages_before_hello_are_ignored():
    hub, calls = mkhub()
    hub.apply_session(ev("s1", "box"))
    link = FakeLink("usb")
    hub.attach(link)
    hub.on_message(link, {"v": 1, "type": "focus", "id": "s1"})
    await settle()
    assert calls == [] and link.sent == []


async def test_closed_tab_is_removed_and_next_box_tries_the_next():
    t = [0.0]
    calls = []
    gone = {"U-ghost"}
    hub = Hub(Board(clock=lambda: t[0]),
              focus=lambda term: calls.append(term["ref"]) or ("missing" if term["ref"] in gone else "ok"))
    hub.apply_session(ev("ghost", "box"))
    t[0] = 1
    hub.apply_session(ev("real", "box"))
    usb = connect(hub, "usb")
    await settle()
    hub.on_message(usb, {"v": 1, "type": "focus_next_waiting"})
    for _ in range(50):
        await asyncio.sleep(0.01)
        if len(calls) >= 2:
            break
    await settle(10)
    assert calls == ["U-ghost", "U-real"]
    assert hub.board.get("ghost") is None
    assert [s["id"] for s in usb.last()["sessions"]] == ["real"] or usb.types().count("board") >= 2


async def test_focus_error_keeps_session():
    calls = []
    hub = Hub(Board(clock=lambda: 0.0), focus=lambda term: calls.append(term) or "error")
    hub.apply_session(ev("a", "box"))
    usb = connect(hub, "usb")
    hub.on_message(usb, {"v": 1, "type": "focus", "id": "a"})
    for _ in range(20):
        await asyncio.sleep(0.01)
    assert hub.board.get("a") is not None


async def test_title_watcher_updates_board_and_broadcasts():
    from pitwall.server import title_watcher
    hub, _ = mkhub()
    hub.apply_session(ev("s1", "green", ref="R1"))
    usb = connect(hub, "usb")
    await settle()
    task = asyncio.create_task(title_watcher(hub, titles=lambda: {"R1": "Fix login bug"}, interval_s=0.01))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if usb.last()["sessions"][0].get("title"):
            break
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert usb.last()["sessions"][0]["title"] == "Fix login bug"


async def test_focus_error_is_logged_with_a_hint(caplog):
    import logging
    caplog.set_level(logging.INFO, logger="pitwall.hub")
    hub = Hub(Board(clock=lambda: 0.0), focus=lambda term: "error")
    hub.apply_session(ev("a", "box"))
    usb = connect(hub, "usb")
    hub.on_message(usb, {"v": 1, "type": "focus", "id": "a"})
    for _ in range(20):
        await asyncio.sleep(0.01)
    assert any("Automation" in r.message for r in caplog.records if r.levelno >= logging.INFO)


async def test_label_from_event_when_no_cwd():
    hub, _ = mkhub()
    hub.apply_session({"type": "session", "agent": "x", "id": "z", "state": "green", "label": "my-agent",
                       "cwd": "", "terminal": None})
    assert hub.board.snapshot()["sessions"][0]["label"] == "my-agent"
