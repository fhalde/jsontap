from typing import Any

import ijson

from .frontend import AsyncJsonNode
from .store import PathStore
from .adapter import AsyncIterableFileLike


class AsyncParser:
    def __init__(self, stream, store: PathStore):
        self._events = ijson.parse_async(AsyncIterableFileLike(stream))
        self._result = {}
        self._store = store

    async def _next_event(self):
        return await anext(self._events)

    def parse(self):
        return AsyncJsonNode((), self._store)

    async def parse_value(self, prefix: tuple[str | int, ...]) -> Any:
        _, event, value = await self._next_event()
        # recurse into object handling
        if event == "start_map":
            node = await self.parse_object(prefix)
            # self._store.set(prefix, node)
            # self._result[prefix] = node
            return node
        # recurse into array handling
        elif event == "start_array":
            node = await self.parse_array(prefix)
            # self._store.set(prefix, node)
            # self._result[prefix] = node
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
            if event == "end_array":
                break
            self._store.begin_item(prefix)
            # recurse into object handling
            if event == "start_map":
                arr.append(await self.parse_object((*prefix, index)))
                index += 1
            # recurse into array handling
            elif event == "start_array":
                arr.append(await self.parse_array((*prefix, index)))
                index += 1
            # primitives
            else:
                arr.append(value)
                self._store.set((*prefix, index), value)
                self._result[(*prefix, index)] = value  # noqa: B904
                index += 1

        self._store.set(prefix, arr)
        self._result[prefix] = arr
        return arr
