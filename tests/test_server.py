import asyncio
import io

from conftest import fixture_bytes
from pitwall.hook import run_hook
from pitwall.protocol import LineDecoder, encode, hello_device
from pitwall.server import serve


async def read_until(reader, pred, timeout=3.0):
    dec = LineDecoder()
    async def loop():
        while True:
            data = await reader.read(4096)
            assert data, "connection closed"
            for m in dec.feed(data):
                if pred(m):
                    return m
    return await asyncio.wait_for(loop(), timeout)


async def test_serve_replaces_stale_socket_and_accepts_hook(short_tmp):
    (short_tmp / "pitwall.sock").write_text("")
    (short_tmp / "devices.sock").write_text("")
    task = asyncio.create_task(serve(short_tmp, watchers=[]))
    try:
        for _ in range(100):
            if (short_tmp / "devices.sock").is_socket():
                break
            await asyncio.sleep(0.02)
        reader, writer = await asyncio.open_unix_connection(str(short_tmp / "devices.sock"))
        writer.write(encode(hello_device("sim", "S1", "socket", {})))
        await writer.drain()
        await read_until(reader, lambda m: m["type"] == "board")
        env = {"ITERM_SESSION_ID": "w0t0p0:U1"}
        rc = await asyncio.to_thread(run_hook, io.BytesIO(fixture_bytes("Stop")), env, short_tmp / "pitwall.sock")
        assert rc == 0
        m = await read_until(reader, lambda m: m["type"] == "board" and m["sessions"])
        assert m["sessions"][0]["state"] == "done" and m["sessions"][0]["label"] == "api"
        assert oct((short_tmp / "devices.sock").stat().st_mode & 0o777) == oct(0o600)
        writer.close()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_second_serve_refuses_and_leaves_first_alone(short_tmp):
    from pitwall.server import AlreadyRunning
    first = asyncio.create_task(serve(short_tmp, watchers=[]))
    try:
        for _ in range(100):
            if (short_tmp / "devices.sock").is_socket():
                break
            await asyncio.sleep(0.02)
        ino = (short_tmp / "pitwall.sock").stat().st_ino
        try:
            await asyncio.wait_for(serve(short_tmp, watchers=[]), 2)
            raise AssertionError("second serve should refuse")
        except AlreadyRunning:
            pass
        assert (short_tmp / "pitwall.sock").stat().st_ino == ino
        reader, writer = await asyncio.open_unix_connection(str(short_tmp / "devices.sock"))
        writer.write(encode(hello_device("sim", "S1", "socket", {})))
        await writer.drain()
        await read_until(reader, lambda m: m["type"] == "board")
        writer.close()
    finally:
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
    assert not (short_tmp / "pitwall.sock").exists()
