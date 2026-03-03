import asyncio

from .store import Store
from .parser import AsyncParser


class FakeChatCompletion:
    """Mimics real API streams (class-based async iterator, not async generator)."""

    def __init__(self, data: str, chunk_size: int = 1):
        self._data = data
        self._chunk_size = chunk_size
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if self._i >= len(self._data):
            raise StopAsyncIteration
        chunk = self._data[self._i : self._i + self._chunk_size]
        self._i += self._chunk_size
        print(repr(chunk), flush=True)
        await asyncio.sleep(0.1)
        return chunk


async def main():
    def jsontap(s):
        store = Store()
        parser = AsyncParser(s, store)
        asyncio.create_task(parser.parse_value(()))
        return parser.parse()

    stream = FakeChatCompletion('{"name": "Alice"}', chunk_size=3)
    parser = jsontap(stream)
    print(await parser["name"])


if __name__ == "__main__":
    asyncio.run(main())
