class AsyncIterableFileLike:
    def __init__(self, stream):
        self._iter = stream.__aiter__()

    async def read(self, n=-1):
        if n == 0:
            return ""
        try:
            return await anext(self._iter)
        except StopAsyncIteration:
            return ""
