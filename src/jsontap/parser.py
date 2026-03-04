from typing import Any

import asyncio
import ijson

from .store import PathStore


class AsyncParser:
    def __init__(self, store: PathStore):
        self._events = ijson.sendable_list()
        self._coro = ijson.parse_coro(self._events)
        self._queue = asyncio.Queue()
        self._store = store

    async def parse(self):
        return await self.parse_value(())

    async def _next_event(self) -> tuple[str, str, Any]:
        return await self._queue.get()

    def feed(self, chunk: str) -> None:
        self._coro.send(chunk.encode("utf-8"))
        for e in self._events:
            self._queue.put_nowait(e)
        del self._events[:]

    async def parse_value(self, prefix: tuple[str | int, ...]) -> Any:
        _, event, value = await self._next_event()
        if event == "start_map":
            node = await self.parse_object(prefix)
            return node
        elif event == "start_array":
            node = await self.parse_array(prefix)
            return node
        else:
            self._store.set(prefix, value)
            return value

    async def parse_object(self, prefix: tuple[str | int, ...]) -> dict[str | int, Any]:
        obj = {}
        while True:
            _, event, value = await self._next_event()
            if event == "map_key":
                obj[value] = await self.parse_value((*prefix, value))
            elif event == "end_map":
                break

        self._store.set(prefix, obj)
        return obj

    async def parse_array(self, prefix: tuple[str | int, ...]) -> list[Any]:
        arr = []
        index = 0
        while True:
            _, event, value = await self._next_event()
            if event == "end_array":
                break
            self._store.begin_item(prefix)
            if event == "start_map":
                arr.append(await self.parse_object((*prefix, index)))
                index += 1
            elif event == "start_array":
                arr.append(await self.parse_array((*prefix, index)))
                index += 1
            else:
                arr.append(value)
                self._store.set((*prefix, index), value)
                index += 1

        self._store.set(prefix, arr)
        return arr
