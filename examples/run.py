import asyncio
from jsontap import jsontap
import json


async def chat_completion():
    payload = {
        "intent": "refund_request",
        "reply_preview": "I can help with that...",
        "steps": ["verify_order", "check_policy", "offer_refund"],
        "final_reply": "I reviewed your order... and approved a refund.",
    }
    for c in json.dumps(payload):
        yield c
        await asyncio.sleep(0.1)


async def agent():
    response = jsontap(chat_completion())

    intent = await response["intent"]
    print(f"[ROUTING] -> {intent}")

    preview = await response["reply_preview"]
    print(f"[PREVIEW] {preview}")

    async for step in response["steps"]:
        print(f"[STEP] {await step}")

    final_reply = await response["final_reply"]
    print(f"[FINAL] {final_reply}")


asyncio.run(agent())
