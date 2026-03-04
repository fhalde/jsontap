import asyncio
import json

from collections.abc import AsyncIterable

from .frontend import AsyncJsonNode
from .parser import AsyncParser
from .store import PathStore


def jsontap(stream: AsyncIterable[str]) -> AsyncJsonNode:
    """
    Parse streamed JSON text in the background and return a path-addressable,
    awaitable root node.

    Args:
        stream: Async iterable yielding raw JSON text chunks.

    Returns:
        AsyncJsonNode: Root node for progressive JSON access via `await` and
        `async for`.

    Notes:
        Starts background tasks immediately:
        - one task feeds incoming token text to the parser
        - one task parses events and resolves node futures
    """
    store = PathStore()
    parser = AsyncParser(store)

    async def feed():
        async for chunk in stream:
            if chunk:
                parser.feed(chunk)

    asyncio.create_task(feed())
    asyncio.create_task(parser.parse())
    return AsyncJsonNode((), store)


async def main():
    data = {
        "scores": [
            {"name": "Alice", "score": 10, "exams": ["Math", "English"]},
            {"name": "Bob", "score": 20, "exams": ["Math", "English"]},
            {"name": "Charlie", "score": 30, "exams": ["Math", "English"]},
        ]
    }

    async def chat_completion():
        for chunk in json.dumps(data):
            yield chunk
            await asyncio.sleep(0.1)

    async for item in jsontap(chat_completion())["scores"]:
        print(await item["score"])
        async for exam in item["exams"]:
            print(await exam)


if __name__ == "__main__":
    asyncio.run(main())
