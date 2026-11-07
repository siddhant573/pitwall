from pitwall.board import Board
from fakes import session_event

TERM = {"kind": "iterm2", "ref": "U"}


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def ev(id, state, cwd=None, terminal=TERM):
    return session_event("claude-code", id, state, "", cwd or f"/w/{id}", terminal)


def make():
    c = Clock()
    return Board(clock=c, ttl_s=100), c


def test_sort_order_and_counts():
    b, c = make()
    b.apply(ev("a", "green"))
    b.apply(ev("b", "box"))
    c.t = 5
    b.apply(ev("c", "box"))
    b.apply(ev("d", "red"))
    b.apply(ev("e", "done"))
    c.t = 10
    snap = b.snapshot()
    assert snap["type"] == "board"
    assert [s["id"] for s in snap["sessions"]] == ["b", "c", "d", "e", "a"]
    assert snap["counts"] == {"box": 2, "red": 1, "done": 1, "green": 1}
    assert snap["sessions"][0]["age_s"] == 10
    assert set(snap["sessions"][0]) == {"id", "label", "title", "state", "age_s", "focusable"}


def test_ties_sorted_by_label():
    b, _ = make()
    b.apply(ev("z", "done", cwd="/w/beta"))
    b.apply(ev("y", "done", cwd="/w/alpha"))
    assert [s["label"] for s in b.snapshot()["sessions"]] == ["alpha", "beta"]


def test_same_folder_labels_get_suffix():
    b, _ = make()
    b.apply(ev("s1", "green", cwd="/w/api"))
    b.apply(ev("s2", "green", cwd="/x/api"))
    labels = {s["id"]: s["label"] for s in b.snapshot()["sessions"]}
    assert labels == {"s1": "api", "s2": "api·2"}


def test_suffix_released_when_first_ends():
    b, _ = make()
    b.apply(ev("s1", "green", cwd="/w/api"))
    b.apply(ev("s2", "green", cwd="/w/api"))
    b.apply(ev("s1", "end"))
    assert b.snapshot()["sessions"][0]["label"] == "api"


def test_same_state_does_not_reset_age_or_report_change():
    b, c = make()
    assert b.apply(ev("a", "box")) is True
    c.t = 4
    assert b.apply(ev("a", "box")) is False
    c.t = 9
    assert b.snapshot()["sessions"][0]["age_s"] == 9


def test_end_removes_and_expire_drops_stale():
    b, c = make()
    b.apply(ev("a", "green"))
    b.apply(ev("b", "green"))
    assert b.apply(ev("a", "end")) is True
    assert b.apply(ev("zz", "end")) is False
    c.t = 50
    b.apply(ev("c", "done"))
    c.t = 101
    assert b.expire() is True
    assert [s["id"] for s in b.snapshot()["sessions"]] == ["c"]
    assert b.expire() is False


def test_next_waiting_is_longest_box():
    b, c = make()
    b.apply(ev("x", "green"))
    assert b.next_waiting() is None
    c.t = 1
    b.apply(ev("b", "box"))
    c.t = 2
    b.apply(ev("c", "box"))
    assert b.next_waiting().id == "b"


def test_unfocusable_without_terminal_and_get():
    b, _ = make()
    b.apply(ev("a", "green", terminal=None))
    assert b.snapshot()["sessions"][0]["focusable"] is False
    assert b.get("a").terminal is None
    assert b.get("missing") is None


def test_invalid_state_ignored():
    b, _ = make()
    assert b.apply(ev("a", "weird")) is False
    assert b.snapshot()["sessions"] == []


def test_titles_by_terminal_ref():
    b, _ = make()
    b.apply(ev("a", "green", cwd="/w/api", terminal={"kind": "iterm2", "ref": "R1"}))
    b.apply(ev("b", "green", cwd="/w/web", terminal=None))
    assert b.snapshot()["sessions"][0]["title"] is None
    assert b.set_titles({"R1": "Fix login bug", "R9": "other"}) is True
    rows = {s["id"]: s for s in b.snapshot()["sessions"]}
    assert rows["a"]["title"] == "Fix login bug" and rows["a"]["label"] == "api"
    assert rows["b"]["title"] is None
    assert b.set_titles({"R1": "Fix login bug"}) is False      # unchanged
    assert b.set_titles({}) is False                            # iTerm unavailable: keep last titles
    assert b.set_titles({"R1": None}) is True                   # tab lost its title
