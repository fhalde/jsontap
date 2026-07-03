import asyncio
from typing import Any
from collections import defaultdict
from attrs import define, field


class _Unset:
    __slots__ = ()

    def __repr__(self):
        return "UNSET"


UNSET = _Unset()

Path = tuple[str | int, ...]


@define
class PathState:
    future = field(factory=lambda: asyncio.get_running_loop().create_future())
    sealed: bool = field(default=False)
    updated = field(factory=lambda: asyncio.Event())
    val: Any = field(default=UNSET)
    error: BaseException | None = field(default=None)

    def pulse(self) -> None:
        """Wake everyone currently waiting on this path."""
        self.updated.set()
        self.updated.clear()

    def resolve(self, value: Any) -> None:
        self.val = value
        self.sealed = True
        self.future.set_result(value)
        self.pulse()

    def fail(self, exc: BaseException) -> None:
        self.error = exc
        self.sealed = True
        self.future.set_exception(exc)
        # mark the exception as retrieved so speculative subscriptions that
        # are never awaited don't emit "exception was never retrieved"
        self.future.exception()
        self.pulse()


def missing(path: Path) -> Exception:
    if path and isinstance(path[-1], int):
        return IndexError("list index out of range")
    return KeyError(".".join(str(p) for p in path))


class PathStore:
    def __init__(self):
        self._nodes: dict[Path, PathState] = defaultdict(PathState)
        self._closed = False
        self._error: BaseException | None = None
        # strong reference to the background parser task, so it can't be
        # garbage-collected mid-parse
        self.task: asyncio.Task | None = None

    def get(self, path: Path) -> PathState:
        state = self._nodes[path]
        if self._closed and not state.future.done():
            # subscribed after parsing already finished: the path was never
            # produced by the stream, resolve it immediately
            state.fail(self._error or missing(path))
        return state

    def set(self, path: Path, value: Any) -> None:
        state = self._nodes[path]
        if state.future.done():
            # duplicate key in the source JSON: the materialized parent keeps
            # the last value, but awaiters already received the first one
            state.val = value
            state.pulse()
            return
        state.resolve(value)

    def begin_item(self, path: Path) -> None:
        state = self._nodes[path]
        if state.val is UNSET:
            state.val = []
        state.val.append(UNSET)
        state.pulse()

    def finish(self, error: BaseException | None = None) -> None:
        """Mark parsing as complete and resolve every pending subscription.

        With no error, pending paths simply don't exist in the parsed JSON
        and fail with KeyError/IndexError. With an error (malformed JSON,
        source exception, truncated stream, cancellation), every pending
        subscription receives that error.
        """
        if self._closed:
            return
        self._closed = True
        self._error = error
        for path, state in self._nodes.items():
            if not state.future.done():
                state.fail(error or missing(path))
