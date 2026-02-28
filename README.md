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

### Async — stream and consume concurrently

Pass any `AsyncIterable[str | bytes]` — an async generator, `aiohttp`'s `resp.content.iter_any()`, `httpx`'s `response.aiter_bytes()`, OpenAI's streaming API, etc.

```python
from jsontap import jsontap

async def agent():
    root = jsontap(llm_token_stream())

    name = await root.user.name
    print(f"Got name early: {name}")

    async for log in root.logs:
        print(f"Streaming log: {log}")
```

`jsontap()` starts a background task that pulls chunks from the source and feeds them to the parser. Values resolve as soon as the relevant bytes have been parsed — no `gather`, no context managers, just `await` what you need.

### Sync — parse then access

For synchronous code (Flask, CLI tools, simple scripts), pass any regular iterable. All chunks are consumed eagerly, then you access values with `.value` and `for` loops:

```python
from jsontap import jsontap

root = jsontap(response.iter_content())

name = root.user.name.value
print(f"Name: {name}")

for log in root.logs:
    print(f"Log: {log}")
```

### Manual feeding

When you control the chunk boundaries yourself:

```python
from jsontap import jsontap

root, feed, finish = jsontap()
feed('{"name":')
feed('"Alice","scores":[1,')
feed('2,3]}')
finish()

name = root.name.value          # "Alice"
scores = list(root.scores)      # [1, 2, 3]
```

### Practical LLM example: interactive agent UI while JSON is still streaming

LLM responses can have noticeable latency and can take a while to finish full structured output. With `jsontap`, your app can react as soon as key fields arrive.

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
    chunks = [
        '{"intent":"refund_request","reply_preview":"I can help',
        ' with that...","steps":["verify_order","check_policy",',
        '"offer_refund"],"final_reply":"I reviewed your order...',
        ' and approved a refund."}',
    ]
    for c in chunks:
        yield c
        await asyncio.sleep(5)

async def run_agent_response():
    root = jsontap(llm_json_stream())

    intent = await root.intent
    print(f"[ROUTING] -> {intent}")

    preview = await root.reply_preview
    print(f"[PREVIEW] {preview}")

    async for step in root.steps:
        print(f"[STEP] {step}")

    final_reply = await root.final_reply
    print(f"[FINAL] {final_reply}")
```

This is where `jsontap` shines for LLM products: immediate UX updates from early fields, while the rest of the JSON is still being generated.

![jsontap streaming demo](show.gif)

## How it works

`jsontap()` returns a reactive root node (`RNode`). Depending on the source:

- **Async iterable** — a background task starts immediately, parsing chunks as they arrive
- **Sync iterable** — all chunks are consumed eagerly, values are resolved before you access them
- **No source** — returns `(root, feed, finish)` for manual chunk-by-chunk feeding

Each node supports these access patterns:

| Pattern | Use case | Example |
|---|---|---|
| `await node` | Get the fully parsed value (scalar, dict, or list) | `name = await root.user.name` |
| `async for item in node` | Stream array elements as they arrive | `async for row in root.rows: ...` |
| `node.value` | Synchronous access to a resolved value | `name = root.user.name.value` |
| `for item in node` | Synchronous iteration over a completed array | `for row in root.rows: ...` |

Nodes are created lazily via attribute access (`root.foo`) or item access (`root["foo"]`) and can be subscribed to before the corresponding JSON has been parsed. Multiple consumers can `await` or iterate the same node concurrently — each gets the full result.

Use `root["key"]` for keys that contain dots, spaces, or collide with RNode attributes like `value` and `resolved`.

### Arrays: stream vs. await

Arrays support both patterns:

```python
# Stream items one by one as they're parsed
async for item in root.logs:
    process(item)

# Or await the full materialized list
all_logs = await root.logs
```

### Nested access

Drill into the tree at any depth:

```python
deep = await root.a.b.c.d
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

**With an async source** — starts background parsing, returns `RNode`:

```python
root = jsontap(async_source)
name = await root.user.name
```

**With a sync source** — parses eagerly, returns `RNode`:

```python
root = jsontap(sync_source)
name = root.user.name.value
```

**No source** — returns `(root, feed, finish)` tuple:

```python
root, feed, finish = jsontap()
feed(chunk)
finish()
```

### `RNode`

| Method / Protocol | Description |
|---|---|
| `node.key` or `node[key]` | Get or create a child node for the given key |
| `await node` | Await the resolved value (blocks until parsed) |
| `async for item in node` | Iterate streamed array items as they arrive |
| `node.value` | Synchronous access to the resolved value |
| `for item in node` | Synchronous iteration over completed array items |
| `node.resolved` | `True` if the node's value has been parsed |

## Requirements

- Python >= 3.12
- [ijson](https://github.com/ICRAR/ijson) >= 3.5
