class AsyncIterableFileLike:
    def __init__(self, stream):
        self._iter = stream.__aiter__()

    async def read(self, n=-1):
        if n == 0:
            return b""
        try:
            chunk = await anext(self._iter)
            return chunk.encode("utf-8") if isinstance(chunk, str) else chunk
        except StopAsyncIteration:
            return b""
