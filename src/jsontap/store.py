import asyncio
from typing import Any
from collections import defaultdict


import attr


@attr
class NodeState:
    future: asyncio.Future[Any] = attr.field(
        default=asyncio.get_running_loop().create_future()
    )
    exception: Exception | None = attr.field(default=None)


Path = tuple[str | int, ...]


class Store:
    def __init__(self):
        self.nodes: dict[Path, NodeState] = defaultdict(NodeState)

    def getdefault(self, path: Path) -> NodeState:
        return self.nodes[path].future

    def set(self, path: Path, value: Any) -> None:
        # this case is not possible, but it's llm and we are parsing partial jsons live
        if self.nodes[path].future.done():
            raise ValueError(
                f"Path {path} already has a value: {self.nodes[path].value}"
            )
        else:
            self.nodes[path].future.set_result(value)
