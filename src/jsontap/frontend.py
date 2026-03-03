from .store import UNSET, PathStore


class AsyncJsonNode:
    def __init__(self, path: tuple[str | int, ...], store: PathStore):
        self.path = path
        self.store = store

    def __getitem__(self, key: str | int) -> "AsyncJsonNode":
        return AsyncJsonNode(path=(*self.path, key), store=self.store)

    def __await__(self):
        return self.store.get(self.path).future.__await__()

    def __aiter__(self):
        return Cursor(self.path, self.store)

    __str__ = __repr__ = lambda self: f"AsyncJN({self.path})"


class Cursor:
    def __init__(self, path, store: PathStore) -> None:
        self.index = 0
        self.path = path
        self.store = store

    async def __anext__(self):
        state = self.store.get(self.path)
        while True:
            while state.val == UNSET:
                await state.updated.wait()
            curr = self.index
            N = len(state.val)
            consumed = curr == N
            if state.sealed and consumed:
                raise StopAsyncIteration
            self.index += 1
            return AsyncJsonNode((*self.path, curr), self.store)
