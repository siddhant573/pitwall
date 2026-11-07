import asyncio


class FakeLink:
    def __init__(self, transport):
        self.transport = transport
        self.sent = []
        self.closed = False

    async def send(self, data: bytes):
        from pitwall.protocol import LineDecoder
        self.sent += LineDecoder().feed(data)

    async def close(self):
        self.closed = True

    def types(self):
        return [m["type"] for m in self.sent]

    def last(self):
        return self.sent[-1]


async def settle(n=5):
    for _ in range(n):
        await asyncio.sleep(0)


def session_event(agent, id, state, label, cwd, terminal):
    return {"type": "session", "agent": agent, "id": id, "state": state,
            "label": label, "cwd": cwd, "terminal": terminal}
