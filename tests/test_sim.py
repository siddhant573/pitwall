from pitwall.sim import sim_key

S = [{"id": "a"}, {"id": "b"}, {"id": "c"}]


def test_n_sends_focus_next_waiting():
    assert sim_key("n", S, 0) == (0, {"type": "focus_next_waiting"})


def test_enter_focuses_selected():
    assert sim_key("enter", S, 1) == (1, {"type": "focus", "id": "b"})
    assert sim_key("enter", [], 0) == (0, None)


def test_arrows_move_and_clamp():
    assert sim_key("down", S, 0) == (1, None)
    assert sim_key("down", S, 2) == (2, None)
    assert sim_key("up", S, 0) == (0, None)
    assert sim_key("x", S, 1) == (1, None)
