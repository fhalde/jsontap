import asyncio
from typing import Any


class Store:
    def __init__(self):
        self.data: dict[tuple[str | int, ...], asyncio.Future[Any]] = {}

    def getdefault(self, path: tuple[str | int, ...]) -> asyncio.Future[Any]:
        if path not in self.data:
            self.data[path] = asyncio.get_running_loop().create_future()
        return self.data[path]

    def set(self, path: tuple[str | int, ...], value: Any) -> None:
        self.getdefault(path).set_result(value)
