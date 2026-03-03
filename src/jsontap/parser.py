import asyncio
from typing import Any

import ijson

from jsontap.frontend import AsyncJsonNode
from jsontap.store import Store


class AsyncIterableFileLike:
    def __init__(self, stream):
        self._iter = stream.__aiter__()

    async def read(self, n=-1):
        if n == 0:
            return b""
        try:
            chunk = await anext(self._iter)
            return chunk.encode("utf-8") if isinstance(chunk, str) else chunk
        except StopAsyncIteration:
            return b""


class AsyncParser:
    def __init__(self, stream, store: Store):
        self._events = ijson.parse_async(AsyncIterableFileLike(stream))
        self._result = {}
        self._store = store

    async def _next_event(self):
        return await anext(self._events)

    async def parse(self):
        asyncio.create_task(self.parse_value(()))
        return AsyncJsonNode((), self._store)

    async def parse_value(self, prefix: tuple[str | int, ...]) -> Any:
        _, event, value = await self._next_event()
        # recurse into object handling
        if event == "start_map":
            node = await self.parse_object(prefix)
            self._store.set(prefix, node)
            self._result[prefix] = node
            return node
        # recurse into array handling
        elif event == "start_array":
            node = await self.parse_array(prefix)
            self._store.set(prefix, node)
            self._result[prefix] = node
            return node
        # primitives
        else:
            self._store.set(prefix, value)
            self._result[prefix] = value
            return value

    async def parse_object(self, prefix: tuple[str | int, ...]) -> dict[str | int, Any]:
        obj = {}
        while True:
            _, event, value = await self._next_event()
            # go back to parse_value for handling this key's value
            if event == "map_key":
                obj[value] = await self.parse_value((*prefix, value))
            # done with this object, return the result
            elif event == "end_map":
                break

        self._store.set(prefix, obj)
        self._result[prefix] = obj
        return obj

    async def parse_array(self, prefix: tuple[str | int, ...]) -> list[Any]:
        arr = []
        index = 0
        while True:
            _, event, value = await self._next_event()
            # recurse into object handling
            if event == "start_map":
                arr.append(await self.parse_object((*prefix, index)))
                index += 1
            # recurse into array handling
            elif event == "start_array":
                arr.append(await self.parse_array((*prefix, index)))
                index += 1
            # done with this array, return the result
            elif event == "end_array":
                break
            # primitives
            else:
                arr.append(value)
                self._store.set((*prefix, index), value)
                self._result[(*prefix, index)] = value  # noqa: B904
                index += 1

        self._store.set(prefix, arr)
        self._result[prefix] = arr
        return arr


def example():
    async def simulate_stream(json_str: str, chunk_size: int = 3):
        """Simulate an LLM streaming JSON character-by-character (or in small chunks)."""
        for i in range(0, len(json_str), chunk_size):
            chunk = json_str[i : i + chunk_size]
            print(repr(chunk), flush=True)
            await asyncio.sleep(0.1)
            yield chunk

    async def main():
        test_json = '{"name": "Alice", "age": 30, "tags": ["admin", "user"], "address": {"city": "NYC"}}'

        p = AsyncParser(simulate_stream(test_json))
        await p.parse()
        print("\nResult:")
        for path, value in sorted(p._result.items(), key=lambda x: str(x[0])):
            print(f"  {path} -> {value!r}")

    asyncio.run(main())


# example()
