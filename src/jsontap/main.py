import asyncio
import json

from .store import PathStore
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
        # print(repr(chunk), flush=True)
        await asyncio.sleep(0.1)
        return chunk


async def main():
    def jsontap(s):
        store = PathStore()
        parser = AsyncParser(s, store)
        asyncio.create_task(parser.parse_value(()))
        return parser.parse()

    d = {
        "user": {
            "name": "Alice",
            "age": 30,
            "scores": [10, 20, 30],
            "children": [{"name": "Bob", "age": 10}, {"name": "Charlie", "age": 12}],
            "address": {"city": "NYC", "state": "NY", "zip": "10001"},
        }
    }
    stream = FakeChatCompletion(json.dumps(d), chunk_size=3)
    parser = jsontap(stream)

    async for i in parser["user"]["scores"]:
        print("item is here!!")
        print(i)
    print(await parser["user"]["name"])
    print(await parser["user"]["age"])
    print(await parser["user"]["scores"])
    print(await parser["user"]["children"][0]["name"])
    print(await parser["user"]["children"][1]["age"])
    print(await parser["user"]["address"]["state"])
    print(await parser["user"]["address"]["city"])
    print(await parser["user"]["address"]["zip"])
    print(await parser["user"]["address"])
    print(await parser["user"])


if __name__ == "__main__":
    asyncio.run(main())
