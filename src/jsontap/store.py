import asyncio
from typing import Any
from collections import defaultdict
from attrs import define, field


"""
for arrays,

when a user does

async for x in j["arr"]:

__aiter__ is called
__anext__ is called

__anext__ starts at i = 0

it blocks if i <= len(arr)

when a item is added (primitive, start array, start map)
arr is extended to len(arr) + 1
__anext__ must be resumed to return a AsyncJsonNode((*path, i))


{
    "seq": true/false
    "future": <fut>
    "val": val
}

"""


@define
class UNSET:
    pass


# good to split pathstate and seqstate. the overloading and if conditionals is a threat to sanity
@define
class PathState:
    future = field(factory=lambda: asyncio.get_running_loop().create_future())
    sealed: bool = field(default=False)
    updated = field(factory=lambda: asyncio.Event())
    val: Any = field(default=UNSET)


Path = tuple[str | int, ...]


class PathStore:
    def __init__(self):
        self.nodes: dict[Path, PathState] = defaultdict(PathState)

    def get(self, path: Path) -> PathState:
        return self.nodes[path]

    def set(self, path: Path, value: Any) -> None:
        # this case is not possible, but it's llm and we are parsing partial jsons live
        # check why root is set twice
        state = self.nodes[path]
        if state.future.done():
            raise ValueError(f"Path {path} already has a value: {state.val}")
        else:
            state.val = value
            state.sealed = True
            state.future.set_result(value)

    def _setclear(self, e: asyncio.Event):
        e.set()
        e.clear()

    def begin_item(self, path: Path) -> None:
        state = self.nodes[path]
        if state.val == UNSET:
            state.val = []
        state.val += [UNSET]
        self._setclear(self.nodes[path].updated)

    def setitem(self, path: Path, index: int, value: Any) -> None:
        pass
