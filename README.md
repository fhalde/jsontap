# jsontap

Reactive access to incrementally parsed JSON for Python. Consume fields and array items as they arrive — no need to wait for the full payload.

`jsontap` builds a reactive node tree on top of [ijson](https://github.com/ICRAR/ijson)'s streaming parser. You `await` scalar/object values and `async for` over arrays while the JSON is still being fed in, one chunk at a time. This makes it ideal for LLM token streams, chunked HTTP responses, or any scenario where JSON arrives incrementally.

## Install

```bash
pip install jsontap
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add jsontap
```

## Quick start

### With an async iterable (e.g. LLM stream)

`source` can be any `AsyncIterable[str | bytes]` — an async generator, `aiohttp`'s `resp.content.iter_any()`, `httpx`'s `response.aiter_bytes()`, OpenAI's streaming API, etc.

```python
import asyncio
from jsontap import jsontap

async def main():
    root, run = jsontap(llm_token_stream())

    async def consume():
        name = await root["user"]["name"]
        print(f"Got name early: {name}")

        async for log in root["logs"]:
            print(f"Streaming log: {log}")

    await asyncio.gather(run(), consume())
```

`run()` pulls chunks from the async iterable and feeds them to the parser. `consume()` runs concurrently — values resolve as soon as the relevant bytes have been parsed.

### Practical LLM example: interactive agent UI while JSON is still streaming

In general, LLM responses can have noticeable latency and can take a while to finish full structured output. With `jsontap`, your app can react as soon as key fields arrive.

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

async def llm_json_stream():
    # Simulated token/chunk stream from an LLM provider.
    chunks = [
        '{"intent":"refund_request","reply_preview":"I can help',
        ' with that...","steps":["verify_order","check_policy",',
        '"offer_refund"],"final_reply":"I reviewed your order...',
        ' and approved a refund."}',
    ]
    for c in chunks:
        yield c
        await asyncio.sleep(5)

async def route_ticket(intent: str):
    print(f"[ROUTING] -> {intent}")

async def push_preview(text: str):
    print(f"[PREVIEW] {text}")

async def push_step(step: str):
    print(f"[STEP] {step}")

async def run_agent_response():
    root, run = jsontap(llm_json_stream())

    async def ui_logic():
        # 1) Early interactivity: route as soon as intent is parsed.
        intent = await root["intent"]
        await route_ticket(intent)

        # 2) Show partial user-visible text early.
        preview = await root["reply_preview"]
        await push_preview(preview)

        # 3) Stream plan/tool steps as they appear.
        async for step in root["steps"]:
            await push_step(step)

        # 4) Full completion still available at the end.
        final_reply = await root["final_reply"]
        print(f"[FINAL] {final_reply}")

    await asyncio.gather(run(), ui_logic())

asyncio.run(run_agent_response())
```

This is where `jsontap` shines for LLM products: immediate UX updates from early fields, while the rest of the JSON is still being generated.

![jsontap streaming demo](show.gif)

### With manual feeding

```python
from jsontap import jsontap

root, feed, finish = jsontap()

feed('{"name":')
feed('"Alice","scores":[1,')
feed('2,3]}')
finish()

name = await root["name"]        # "Alice"
scores = await root["scores"]    # [1, 2, 3]
```

## How it works

`jsontap()` returns a **reactive root node** (`RNode`). Each node supports two access patterns:

| Pattern | Use case | Example |
|---|---|---|
| `await node` | Get the fully parsed value (scalar, dict, or list) | `name = await root["user"]["name"]` |
| `async for item in node` | Stream array elements as they arrive | `async for row in root["rows"]: ...` |

Nodes are created lazily via `__getitem__` and can be subscribed to before the corresponding JSON has been parsed. Multiple consumers can `await` or iterate the same node concurrently — each gets the full result.

### Arrays: stream vs. await

Arrays support both patterns:

```python
# Stream items one by one as they're parsed
async for item in root["logs"]:
    process(item)

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

## API reference

### `jsontap(source=None)`

Creates a reactive JSON root and its feeder.

**With source** (`AsyncIterable[str | bytes]` — any object you can `async for` over):

```python
root, run = jsontap(source)
# root: RNode — the reactive root
# run:  async callable — drives the parser; await it or gather with consumers
```

**Without source** (manual feeding):

```python
root, feed, finish = jsontap()
# root:   RNode — the reactive root
# feed:   callable(chunk) — push a str or bytes chunk
# finish: callable() — signal end of input
```

### `RNode`

| Method / Protocol | Description |
|---|---|
| `node[key]` | Get or create a child node for the given key |
| `await node` | Await the resolved value (blocks until parsed) |
| `async for item in node` | Iterate streamed array items |

## Requirements

- Python >= 3.12
- [ijson](https://github.com/ICRAR/ijson) >= 3.5
