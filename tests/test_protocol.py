from pitwall.protocol import (LineDecoder, encode, split_chunks,
                              board, alert, focus, focus_next_waiting, hello_device, hello_helper)


def test_encode_roundtrip_and_version():
    data = encode({"type": "focus", "id": "a"})
    assert data.endswith(b"\n")
    assert LineDecoder().feed(data) == [{"type": "focus", "id": "a", "v": 1}]


def test_decoder_skips_garbage_and_wrong_version():
    d = LineDecoder()
    out = d.feed(b'\x00{garbage\n{"v":2,"type":"x"}\nhello\n[1,2]\n\n{"v":1,"type":"ping"}\n')
    assert out == [{"v": 1, "type": "ping"}]


def test_decoder_handles_partial_lines():
    d = LineDecoder()
    assert d.feed(b'{"v":1,"ty') == []
    assert d.feed(b'pe":"ping"}\n') == [{"v": 1, "type": "ping"}]


def test_utf8_split_across_chunks_reassembles_exactly():
    line = encode({"type": "board", "sessions": [{"label": "café-🏎️-api"}], "counts": {}})
    chunks = split_chunks(line, 7)
    assert all(len(c) <= 7 for c in chunks)
    assert b"".join(chunks) == line
    d = LineDecoder()
    out = []
    for c in chunks:
        out += d.feed(c)
    assert out[0]["sessions"][0]["label"] == "café-🏎️-api"


def test_message_builders():
    assert board([], {"box": 0}) == {"type": "board", "sessions": [], "counts": {"box": 0}}
    assert alert("s1") == {"type": "alert", "id": "s1"}
    assert focus("s1") == {"type": "focus", "id": "s1"}
    assert focus_next_waiting() == {"type": "focus_next_waiting"}
    assert hello_device("badger2350", "B1", "usb", {"keys": 0}) == {
        "type": "hello", "device": "badger2350", "uid": "B1", "transport": "usb", "caps": {"keys": 0}}
    assert hello_helper()["type"] == "hello" and hello_helper()["device"] == "helper"
