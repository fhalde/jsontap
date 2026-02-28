# jsontap

Structured, awaitable access to streaming JSON sources.

Consume fields and array items as they arrive – no need to wait for the full payload. Built on top of streaming parsing from [ijson](https://github.com/ICRAR/ijson), you can `await` values or `async for` over arrays as the JSON arrives incrementally, making it ideal for LLM token streams.

## Why Use jsontap?

Traditional JSON parsing (e.g., `json.loads`) requires the complete payload before parsing and processing can continue, preventing progressive execution when working with streaming sources like LLM responses. 

**jsontap** allows you to consume structured JSON while it is still streaming:

- Await individual fields as they arrive
- Async-iterate arrays in real time
- Start responding before the full JSON is done

## Install

```bash
pip install jsontap
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add jsontap
```

## Quick start

### Practical LLM example

LLM responses can have noticeable latency and can take a while to finish full structured output. With **jsontap**, your app can react as soon as key fields arrive.

Suppose your model streams JSON like:

```json
{
  "intent": "refund_request",
  "reply_preview": "I can help with that...",
  "steps": ["verify_order", "check_policy", "offer_refund"],
  "final_reply": "..."
}
```

You can route and update UI early, then stream plan steps, without waiting for `final_reply`.

```python
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
```

This is where `jsontap` stands out for LLM products: it enables immediate handling of fields, even as the rest of the JSON continues generating — all while letting developers write code that feels clean and sequential.

![jsontap streaming demo](show.gif)

## How it works

`jsontap()` returns a reactive root node (`AsyncJsonNode`). Depending on the source:

- **Async iterable** — a background task starts immediately, parsing chunks as they arrive
- **Sync iterable** — all chunks are consumed eagerly, values are resolved before you access them
- **No source** — returns `(root, feed, finish)` for manual chunk-by-chunk feeding

Each node supports these access patterns:

| Pattern | Use case | Example |
|---|---|---|
| `await node` | Get the fully parsed value (scalar, dict, or list) | `name = await root["user"]["name"]` |
| `async for item in node` | Stream array item handles (`AsyncJsonNode`) as each slot appears | `async for row in root["rows"]: ...` |
| `async for value in node.values()` | Stream completed array values directly | `async for row in root["rows"].values(): ...` |
| `node.value` | Synchronous access to a resolved value | `name = root["user"]["name"].value` |
| `for item in node` | Synchronous iteration over a completed array | `for row in root["rows"]: ...` |

Nodes are created lazily via `node["key"]` and can be subscribed to before the corresponding JSON has been parsed. Multiple consumers can `await` or iterate the same node concurrently — each gets the full result.

### Arrays: handles vs. values vs. await

Arrays support both patterns:

```python
# Default async iteration yields item handles.
async for item in root["logs"]:
    if await item["type"] == "error":
        alert(await item["message"])

# If you want fully materialized values from async iteration:
async for log in root["logs"].values():
    process(log)

# Or await the full materialized list
all_logs = await root["logs"]
```

### Nested access

Drill into the tree at any depth:

```python
deep = await root["a"]["b"]["c"]["d"]
```

Child nodes are created on first access, so you can subscribe before the parent has been fully parsed.

## Replay behavior

`jsontap` keeps streamed array items in memory so late subscribers can replay full history.

## Error handling

- If the source raises, or the JSON is malformed, all pending `await`s and `async for` loops receive the exception immediately.
- Accessing a key that doesn't exist in the parsed JSON raises `KeyError` once parsing is complete.
- Calling `feed()` after `finish()` raises `RuntimeError`.
- Accessing `.value` before a node is resolved raises `LookupError`.
- Calling `for ... in node` before the stream is complete raises `RuntimeError`.

## API reference

### `jsontap(source=None)`

Creates a reactive JSON root.

**With an async source** — starts background parsing, returns `AsyncJsonNode`:

```python
root = jsontap(async_source)
name = await root["user"]["name"]
```

**With a sync source** — parses eagerly, returns `AsyncJsonNode`:

```python
root = jsontap(sync_source)
name = root["user"]["name"].value
```

**No source** — returns `(root, feed, finish)` tuple:

```python
root, feed, finish = jsontap()
feed(chunk)
finish()
```

### `AsyncJsonNode`

| Method / Protocol | Description |
|---|---|
| `node["key"]` | Get or create a child node for the given key |
| `await node` | Await the resolved value (blocks until parsed) |
| `async for item in node` | Iterate streamed array item handles (`AsyncJsonNode`) |
| `async for value in node.values()` | Iterate streamed array values as they complete |
| `node.value` | Synchronous access to the resolved value |
| `for item in node` | Synchronous iteration over completed array items |
| `node.resolved` | `True` if the node's value has been parsed |
