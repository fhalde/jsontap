import asyncio

from .store import Store
from .parser import AsyncParser


async def main():
    def jsontap(s):
        store = Store()
        parser = AsyncParser(s, store)
        asyncio.create_task(parser.parse_value(()))
        return parser.parse()

    async def chat_completion(json_str: str):
        for char in json_str:
            print(char, end="", flush=True)
            yield char
            await asyncio.sleep(0.1)

    parser = jsontap(chat_completion('{"name": "Alice"}'))
    print(await parser["name"])


if __name__ == "__main__":
    asyncio.run(main())
