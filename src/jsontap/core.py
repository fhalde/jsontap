from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import ijson

_VALUE_EVENTS = frozenset({"string", "number", "boolean", "null"})
_UNSET = object()


@dataclass
class _PathState:
    value: object = _UNSET
    exception: Exception | None = None
    future: asyncio.Future | None = None
    stream_items: list = field(default_factory=list)
    stream_items_by_index: dict[int, object] = field(default_factory=dict)
    progressive_items_by_index: dict[int, tuple[str, ...]] = field(default_factory=dict)
    stream_length: int | None = None
    stream_done: bool = False
    stream_error: Exception | None = None
    stream_waiters: list[asyncio.Future] = field(default_factory=list)
    progressive_waiters: list[asyncio.Future] = field(default_factory=list)
    sealed: bool = False


class _PathStore:
    def __init__(self) -> None:
        self._states: dict[tuple[str, ...], _PathState] = {(): _PathState()}
        self._closed = False

    def get(self, path: tuple[str, ...]) -> _PathState:
        if path not in self._states:
            state = _PathState()
            self._states[path] = state
            if self._closed:
                state.exception = KeyError(
                    f"Missing key in parsed JSON: {self._path_str(path)}"
                )
                state.stream_error = state.exception
                state.stream_done = True
                state.sealed = True
        return self._states[path]

    def ensure_future(self, path: tuple[str, ...]) -> asyncio.Future:
        state = self.get(path)
        if state.future is None:
            state.future = asyncio.get_running_loop().create_future()
            if state.value is not _UNSET:
                state.future.set_result(state.value)
            elif state.exception is not None:
                state.future.set_exception(state.exception)
        return state.future

    def resolve(self, path: tuple[str, ...], value) -> None:
        state = self.get(path)
        if state.value is _UNSET and state.exception is None:
            state.value = value
            if state.future is not None and not state.future.done():
                state.future.set_result(value)

    def fail(self, path: tuple[str, ...], exc: Exception) -> None:
        state = self.get(path)
        if state.exception is None and state.value is _UNSET:
            state.exception = exc
            if state.future is not None and not state.future.done():
                state.future.set_exception(exc)
        state.stream_error = exc
        state.stream_done = True
        self._wake_stream_waiters(state)
        self._wake_progressive_waiters(state)

    def push_stream(self, path: tuple[str, ...], value) -> None:
        state = self.get(path)
        index = len(state.stream_items)
        state.stream_items.append(value)
        state.stream_items_by_index[index] = value
        self._wake_stream_waiters(state)

    def end_stream(self, path: tuple[str, ...], final_value=None) -> None:
        state = self.get(path)
        state.stream_done = True
        if final_value is None:
            final_value = list(state.stream_items)
        state.stream_length = len(final_value)
        if not state.stream_items_by_index:
            for idx, item in enumerate(final_value):
                state.stream_items_by_index[idx] = item
            state.stream_items = list(final_value)
        if not state.progressive_items_by_index:
            for idx in range(state.stream_length):
                state.progressive_items_by_index[idx] = (*path, str(idx))
        self.resolve(path, final_value)
        self._wake_stream_waiters(state)
        self._wake_progressive_waiters(state)

    def push_stream_indexed(self, path: tuple[str, ...], index: int, value) -> None:
        """Insert stream item by index while preserving consumer order."""
        state = self.get(path)
        state.stream_items_by_index[index] = value
        state.stream_items.append(value)
        self._wake_stream_waiters(state)

    def push_progressive_indexed(
        self, path: tuple[str, ...], index: int, item_path: tuple[str, ...]
    ) -> None:
        """Insert progressive item path by index for early item-node iteration."""
        state = self.get(path)
        state.progressive_items_by_index[index] = item_path
        self._wake_progressive_waiters(state)

    def close_missing(self) -> None:
        self._closed = True
        for path, state in self._states.items():
            if state.value is _UNSET and state.exception is None:
                exc = KeyError(f"Missing key in parsed JSON: {self._path_str(path)}")
                state.exception = exc
                if state.future is not None and not state.future.done():
                    state.future.set_exception(exc)
            if not state.stream_done:
                state.stream_done = True
                self._wake_stream_waiters(state)
                self._wake_progressive_waiters(state)
            state.sealed = True

    def close_error(self, exc: Exception) -> None:
        self._closed = True
        for state in self._states.values():
            if state.value is _UNSET and state.exception is None:
                state.exception = exc
                if state.future is not None and not state.future.done():
                    state.future.set_exception(exc)
            state.stream_error = exc
            state.stream_done = True
            state.sealed = True
            self._wake_stream_waiters(state)
            self._wake_progressive_waiters(state)

    @staticmethod
    def _path_str(path: tuple[str, ...]) -> str:
        return "/".join(path) if path else "<root>"

    @staticmethod
    def _wake_stream_waiters(state: _PathState) -> None:
        for waiter in state.stream_waiters:
            if not waiter.done():
                waiter.set_result(None)
        state.stream_waiters.clear()

    @staticmethod
    def _wake_progressive_waiters(state: _PathState) -> None:
        for waiter in state.progressive_waiters:
            if not waiter.done():
                waiter.set_result(None)
        state.progressive_waiters.clear()


class AsyncJsonNode:
    """Awaitable, iterable wrapper over a path-indexed JSON store."""

    def __init__(
        self, store: _PathStore | None = None, path: tuple[str, ...] = ()
    ) -> None:
        self._store = _PathStore() if store is None else store
        self._path = path

    @property
    def path(self) -> tuple[str, ...]:
        return self._path

    @property
    def resolved(self) -> bool:
        state = self._store.get(self._path)
        return state.value is not _UNSET or state.exception is not None

    @property
    def value(self):
        state = self._store.get(self._path)
        if state.value is not _UNSET:
            return state.value
        if state.exception is not None:
            raise state.exception
        raise LookupError("Value not yet resolved. Use 'await node'.")

    def __getitem__(self, key: str | int) -> AsyncJsonNode:
        return AsyncJsonNode(self._store, (*self._path, str(key)))

    def __await__(self):
        return self._store.ensure_future(self._path).__await__()

    def __aiter__(self):
        return _AsyncPathCursor(self._store, self._path)

    def lazy(self):
        """Iterate array item nodes as soon as their index slots are known."""
        return _AsyncPathNodeCursor(self._store, self._path)

    def __iter__(self):
        state = self._store.get(self._path)
        if not state.stream_done:
            raise RuntimeError("Stream not complete. Use 'async for node' first.")
        if state.stream_error is not None:
            raise state.stream_error
        if state.stream_length is None:
            return iter(state.stream_items)
        ordered = [state.stream_items_by_index[i] for i in range(state.stream_length)]
        return iter(ordered)


class _AsyncPathCursor:
    def __init__(self, store: _PathStore, path: tuple[str, ...]) -> None:
        self._store = store
        self._path = path
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            state = self._store.get(self._path)
            if self._index in state.stream_items_by_index:
                value = state.stream_items_by_index[self._index]
                self._index += 1
                return value

            if state.stream_error is not None:
                raise state.stream_error
            if state.stream_done:
                if (
                    state.stream_length is not None
                    and self._index < state.stream_length
                ):
                    raise RuntimeError(
                        f"Missing array item at index {self._index} for completed stream."
                    )
                raise StopAsyncIteration

            waiter = asyncio.get_running_loop().create_future()
            state.stream_waiters.append(waiter)
            await waiter


class _AsyncPathNodeCursor:
    def __init__(self, store: _PathStore, path: tuple[str, ...]) -> None:
        self._store = store
        self._path = path
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            state = self._store.get(self._path)
            if self._index in state.progressive_items_by_index:
                item_path = state.progressive_items_by_index[self._index]
                self._index += 1
                return AsyncJsonNode(self._store, item_path)

            if state.stream_error is not None:
                raise state.stream_error
            if state.stream_done:
                if (
                    state.stream_length is not None
                    and self._index < state.stream_length
                ):
                    raise RuntimeError(
                        f"Missing progressive item at index {self._index} for completed stream."
                    )
                raise StopAsyncIteration

            waiter = asyncio.get_running_loop().create_future()
            state.progressive_waiters.append(waiter)
            await waiter


class AsyncJsonFeed:
    """Incremental parser that writes updates into a path-indexed store."""

    def __init__(self, root: AsyncJsonNode):
        self.root = root
        self._store = root._store
        self._events = ijson.sendable_list()
        self._parser = ijson.parse_coro(self._events)
        self._stack: list[dict] = []
        self._closed = False

    def _current(self):
        return self._stack[-1] if self._stack else None

    def _next_array_item_slot(self, container: dict) -> tuple[tuple[str, ...], int]:
        idx = container["next_index"]
        container["next_index"] += 1
        return (*container["path"], str(idx)), idx

    def _start_container(self, kind: str) -> None:
        parent = self._current()
        value = {} if kind == "map" else []
        parent_index = None

        if parent is None:
            path = ()
        elif parent["type"] == "map":
            key = parent["key"]
            if key is None:
                raise RuntimeError("Map value started without a map key.")
            path = (*parent["path"], key)
            parent["value"][key] = value
            parent["key"] = None
        else:
            path, parent_index = self._next_array_item_slot(parent)
            parent["value"].append(value)
            self._store.push_progressive_indexed(parent["path"], parent_index, path)

        self._stack.append(
            {
                "type": kind,
                "path": path,
                "value": value,
                "key": None,
                "next_index": 0,
                "index_in_parent": parent_index,
            }
        )

    def _consume_scalar(self, value) -> None:
        parent = self._current()
        if parent is None:
            self._store.resolve((), value)
            return

        if parent["type"] == "map":
            key = parent["key"]
            if key is None:
                raise RuntimeError("Scalar map value arrived without a map key.")
            path = (*parent["path"], key)
            parent["value"][key] = value
            parent["key"] = None
            self._store.resolve(path, value)
            return

        parent["value"].append(value)
        item_path, item_index = self._next_array_item_slot(parent)
        self._store.push_progressive_indexed(parent["path"], item_index, item_path)
        self._store.resolve(item_path, value)
        self._store.push_stream_indexed(parent["path"], item_index, value)

    def _complete_container(self, expected_type: str) -> None:
        if not self._stack:
            raise RuntimeError(f"Unexpected end of {expected_type}.")

        current = self._stack.pop()
        if current["type"] != expected_type:
            raise RuntimeError(
                f"Mismatched container close: expected {current['type']} got {expected_type}."
            )

        completed = current["value"]
        path = current["path"]
        if expected_type == "array":
            self._store.end_stream(path, completed)
        else:
            self._store.resolve(path, completed)

        parent = self._current()
        if parent is not None and parent["type"] == "array":
            self._store.push_stream_indexed(
                parent["path"], current["index_in_parent"], completed
            )

    def _apply_event(self, event: str, value) -> None:
        if event == "start_map":
            self._start_container("map")
            return
        if event == "map_key":
            if self._stack and self._stack[-1]["type"] == "map":
                self._stack[-1]["key"] = value
            return
        if event == "start_array":
            self._start_container("array")
            return
        if event == "end_map":
            self._complete_container("map")
            return
        if event == "end_array":
            self._complete_container("array")
            return
        if event in _VALUE_EVENTS:
            self._consume_scalar(value)

    def feed(self, chunk: str | bytes | bytearray) -> None:
        if self._closed:
            raise RuntimeError("Cannot feed after parser is closed.")
        try:
            data = (
                chunk
                if isinstance(chunk, (bytes, bytearray))
                else chunk.encode("utf-8")
            )
            self._parser.send(data)
        except ijson.IncompleteJSONError:
            return
        except Exception as exc:
            self.close_with_error(exc)
            raise

        for _, event, value in self._events:
            self._apply_event(event, value)
        self._events.clear()

    def finish(self) -> None:
        if self._closed:
            return
        try:
            self._parser.close()
        except ijson.IncompleteJSONError as exc:
            self.close_with_error(exc)
            raise
        except Exception as exc:
            self.close_with_error(exc)
            raise

        for _, event, value in self._events:
            self._apply_event(event, value)
        self._events.clear()
        self._store.close_missing()
        self._closed = True

    def close_with_error(self, exc: Exception) -> None:
        if self._closed:
            return
        self._store.close_error(exc)
        self._closed = True


def jsontap(source=None):
    store = _PathStore()
    root = AsyncJsonNode(store)
    feed = AsyncJsonFeed(root)

    if source is None:
        return root, feed.feed, feed.finish

    if hasattr(source, "__aiter__"):

        async def _drive():
            try:
                async for chunk in source:
                    feed.feed(chunk)
                feed.finish()
            except Exception as exc:
                feed.close_with_error(exc)

        root._task = asyncio.create_task(_drive())
        return root

    for chunk in source:
        feed.feed(chunk)
    feed.finish()
    return root


__all__ = ["AsyncJsonNode", "AsyncJsonFeed", "jsontap"]
