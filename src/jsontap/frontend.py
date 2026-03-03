from .store import Store


class AsyncJsonNode:
    def __init__(self, path: tuple[str | int, ...], store: Store):
        self.path = path
        self.store = store

    def __getitem__(self, key: str | int) -> "AsyncJsonNode":
        return AsyncJsonNode(path=(*self.path, key), store=self.store)

    def __await__(self):
        return self.store.getdefault(self.path).__await__()

    __str__ = __repr__ = lambda self: f"({self.path})"
