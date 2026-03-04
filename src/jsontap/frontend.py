from .store import UNSET, PathStore


class AsyncJsonNode:
    def __init__(self, path: tuple[str | int, ...], store: PathStore):
        self._path = path
        self._store = store

    def __getitem__(self, key: str | int) -> "AsyncJsonNode":
        return AsyncJsonNode(path=(*self._path, key), store=self._store)

    def __await__(self):
        return self._store.get(self._path).future.__await__()

    def values(self):
        async def gen():
            async for item in self:
                yield await item
            return

        return gen()

    def __aiter__(self):
        return Cursor(self._path, self._store)

    __str__ = __repr__ = lambda self: f"AsyncJN({self.path})"


class Cursor:
    def __init__(self, path, store: PathStore) -> None:
        self._index = 0
        self._path = path
        self._store = store

    async def __anext__(self):
        state = self._store.get(self._path)
        while True:
            while state.val == UNSET:
                await state.updated.wait()
            curr = self._index
            N = len(state.val)
            consumed = curr == N
            if state.sealed and consumed:
                raise StopAsyncIteration
            if curr < N:
                self._index += 1
                return AsyncJsonNode((*self._path, curr), self._store)
            else:
                await state.updated.wait()
