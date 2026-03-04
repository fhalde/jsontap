import asyncio
import json
import os

from openai import AsyncOpenAI
from jsontap import jsontap

SCHEMA = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": ["billing", "technical", "account", "general"],
        },
        "urgency": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "action_steps": {"type": "array", "items": {"type": "string"}},
        "full_response": {"type": "string"},
    },
    "required": ["category", "urgency", "action_steps", "full_response"],
    "additionalProperties": False,
}

TICKET = """
My account was charged twice for the same subscription this month and I
can't log in to fix it. I have an important client demo in 2 hours.
"""


async def chat_completion_stream(client: AsyncOpenAI):
    stream = await client.chat.completions.create(
        model="nvidia/nemotron-3-nano-30b-a3b:free",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a support triage assistant. "
                    "Respond only with valid JSON matching the provided schema."
                ),
            },
            {
                "role": "user",
                "content": f"Triage this support ticket:\n\n{TICKET}",
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "support_triage",
                "strict": True,
                "schema": SCHEMA,
            },
        },
        stream=True,
    )

    return stream


async def main():
    client = AsyncOpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )

    print("🚀 Starting ticket triage stream...")
    stream = await chat_completion_stream(client)
    response = jsontap(stream)

    category, urgency = await asyncio.gather(
        response["category"],
        response["urgency"],
    )

    print(f"🧭 Routing -> assigned to '{category}'")
    print(f"⚠️ Urgency -> {urgency.upper()}")

    if urgency in ("high", "critical"):
        print("📟 Alert -> paging on-call engineer")

    print("🛠️ Action steps:")
    async for step in response["action_steps"]:
        print(f"• {await step}")

    full_response = await response["full_response"]
    print(f"✅ Final response -> {full_response}")
    print("🎉 Done.")

    final_json = await response
    print("\n📦 Final JSON:")
    print(json.dumps(final_json, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
