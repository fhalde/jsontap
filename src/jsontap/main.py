import asyncio

from .store import Store
from .parser import AsyncParser


async def main():
    async def simulate_stream(json_str: str):
        for char in json_str:
            print(char, end="", flush=True)
            yield char
            await asyncio.sleep(0.5)

    store = Store()

    parser = AsyncParser(simulate_stream('{"name": "Alice"}'), store)
    json = parser.parse()

    print(await json["name"])


if __name__ == "__main__":
    asyncio.run(main())
