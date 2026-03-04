import asyncio

from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk

from .frontend import AsyncJsonNode
from .parser import AsyncParser
from .store import PathStore


def jsontap(s: AsyncStream[ChatCompletionChunk]):
    store = PathStore()
    parser = AsyncParser(store)

    async def feed():
        async for chunk in s:
            if chunk.choices and (delta := chunk.choices[0].delta) and delta.content:
                parser.feed(delta.content)

    asyncio.create_task(feed())
    asyncio.create_task(parser.parse())
    return AsyncJsonNode((), store)


"""
async def main():
    SCHEMA = {
        "type": "object",
        "properties": {
            "user": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                    "scores": {"type": "array", "items": {"type": "integer"}},
                    "children": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "age": {"type": "integer"},
                            },
                            "required": ["name", "age"],
                            "additionalProperties": False,
                        },
                    },
                    "address": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                            "state": {"type": "string"},
                            "zip": {"type": "string"},
                        },
                        "required": ["city", "state", "zip"],
                        "additionalProperties": False,
                    },
                },
                "required": ["name", "age", "scores", "children", "address"],
                "additionalProperties": False,
            },
        },
        "required": ["user"],
        "additionalProperties": False,
    }
    client = AsyncOpenAI(
        api_key=os.environ.get("OPENAI_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY"),
        base_url=os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
    )

    stream = await client.chat.completions.create(
        model="nvidia/nemotron-3-nano-30b-a3b:free",
        messages=[
            {
                "role": "system",
                "content": (
                    "Generate a realistic user profile matching the provided JSON schema. "
                    "Include at least 3 scores and at least 2 children. Respond only with valid JSON."
                ),
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "user_profile",
                "strict": True,
                "schema": SCHEMA,
            },
        },
        stream=True,
    )

    json = jsontap(stream)
    async for child in json["user"]["children"]:
        print(f"  child: {await child['name']}, age {await child['age']}")

    print("name:", await json["user"]["name"])
    print("age:", await json["user"]["age"])
    print("scores:", await json["user"]["scores"])
    print("city:", await json["user"]["address"]["city"])
    print("state:", await json["user"]["address"]["state"])
    print("zip:", await json["user"]["address"]["zip"])
    print("user:", await json["user"])


if __name__ == "__main__":
    asyncio.run(main())
"""
