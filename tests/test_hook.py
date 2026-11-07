import io
import socket
import threading
import time

from conftest import fixture_bytes, load
from pitwall.agents.claude_code import map_hook
from pitwall.hook import run_hook
from pitwall.protocol import LineDecoder


def test_hook_exits_0_without_helper(short_tmp):
    t = time.perf_counter()
    assert run_hook(io.BytesIO(fixture_bytes("Stop")), {}, short_tmp / "missing.sock") == 0
    assert time.perf_counter() - t < 0.3


def test_hook_exits_0_on_stale_socket_file_and_bad_stdin(short_tmp):
    (short_tmp / "s.sock").write_text("")
    assert run_hook(io.BytesIO(b"not json"), {}, short_tmp / "s.sock") == 0
    assert run_hook(io.BytesIO(fixture_bytes("Stop")), {}, short_tmp / "s.sock") == 0


def test_hook_skips_events_that_change_nothing(short_tmp):
    received = _listen(short_tmp / "h.sock")
    assert run_hook(io.BytesIO(b'{"hook_event_name":"Notification","session_id":"x","notification_type":"auth_success"}'), {}, short_tmp / "h.sock") == 0
    time.sleep(0.2)
    assert received == []


def test_hook_delivers_one_line(short_tmp):
    received = _listen(short_tmp / "h.sock")
    env = {"ITERM_SESSION_ID": "w0t0p0:U1"}
    assert run_hook(io.BytesIO(fixture_bytes("Stop")), env, short_tmp / "h.sock") == 0
    for _ in range(50):
        if received:
            break
        time.sleep(0.02)
    expected = map_hook(load("Stop"), env) | {"v": 1}
    assert received == [expected]


def _listen(path):
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)
    received = []

    def loop():
        srv.settimeout(2)
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        data = b""
        while chunk := conn.recv(4096):
            data += chunk
        received.extend(LineDecoder().feed(data))
        conn.close()

    threading.Thread(target=loop, daemon=True).start()
    return received
