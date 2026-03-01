# jsontap

**Progressively start acting on structured output from an LLM as it streams.**

jsontap lets you `await` individual fields and `async for` over arrays as the JSON streams in – so you can dispatch tool calls, update your UI, or trigger downstream logic the moment each piece arrives, while the model is still generating the rest.

## Install

```bash
pip install jsontap
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add jsontap
```

## The problem with how agents work today

Most agent frameworks handle structured JSON output in one of a few ways:

- **Buffer and parse** – wait for the full streamed response, then call `json.loads`. Simple, but you're leaving tool execution latency sitting idle during generation.
- **One tool call at a time** – prompt the model to return a single tool call, execute it, then go back for the next. Clean, but fully sequential. You lose all parallelism.
- **Newline-delimited hacks** – instruct the model to output one JSON object per line and split on `\n`. Brittle, prompt-dependent, and breaks with any formatting variation.

jsontap eliminates these workarounds with a clean async API that sits directly on top of the stream.

## Your code stays sequential. Your execution doesn't have to be.

The typical alternative to buffering is callback-based or event-driven parsing – you register handlers that fire when certain keys arrive, and your logic gets split across multiple functions. It works, but it inverts how you naturally think about the problem.

jsontap takes a different approach. You write code that reads top-to-bottom, like you're just accessing a dict:

```python
reasoning = await response["reasoning"]
print(f"[PLAN] {reasoning}")

async for call in response["calls"]:
    tool = await call["tool"]
    args = await call["args"]
    asyncio.create_task(dispatch(tool, args))

summary = await response["summary"]
print(f"[DONE] {summary}")
```

This looks like sequential code waiting on a fully-parsed object. It isn't. Each `await` and `async for` resolves as the relevant part of the JSON arrives in the stream – `reasoning` unblocks the moment that field is parsed, the `calls` loop starts iterating before the array is complete, and `summary` waits only as long as it needs to. The stream is being consumed progressively the whole time; your code just doesn't have to look like it.

This matters in practice because it means you can add streaming behavior to an agent without restructuring how you wrote it. If you have existing code that accesses a parsed JSON dict, the jsontap version looks almost identical.

## Practical LLM example

Suppose your model streams a response with multiple tool calls:

```json
{
  "reasoning": "I need to look this up, check the file, and query the database.",
  "calls": [
    {
      "tool": "search_web",
      "args": {
        "query": "Q3 earnings Apple"
      }
    },
    {
      "tool": "read_file",
      "args": {
        "path": "context.txt"
      }
    },
    {
      "tool": "query_db",
      "args": {
        "sql": "SELECT * FROM orders LIMIT 10"
      }
    }
  ]
}
```

Without jsontap, nothing happens until all three calls have been generated. With jsontap, each call is dispatched the moment its object finishes parsing – while the model is still generating the ones that follow:

```python
import asyncio
from jsontap import jsontap

async def agent():
    response = jsontap(stream_from_llm())

    # Optional: log reasoning as soon as it lands
    reasoning = await response["reasoning"]
    print(f"[PLAN] {reasoning}")

    # Dispatch each tool call as it arrives – don't wait for all three
    async for call in response["calls"]:
        tool = await call["tool"]
        args = await call["args"]
        asyncio.create_task(dispatch(tool, args))
```

`calls[0]` starts executing while the model is still generating `calls[2]`. In a multi-step agent loop where tool calls hit real APIs or databases, this overlap compounds across every iteration.

## Other access patterns

jsontap supports several ways to consume nodes depending on what you need:

```python
# Await a scalar field
intent = await response["intent"]

# Await a nested value
city = await response["user"]["address"]["city"]

# Async-iterate array items as handles (access sub-fields per item)
async for item in response["results"]:
    score = await item["score"]
    print(score)

# Async-iterate array as fully materialized values
async for result in response["results"].values():
    process(result)

# Await the full array at once
all_results = await response["results"]
```

Nodes are created lazily and can be subscribed to before their part of the JSON has been parsed. Multiple consumers can `await` or iterate the same node – each gets the full result.

## Manual feeding

If you're managing your own stream (e.g., from a WebSocket or custom transport), you can feed chunks manually:

```python
root, feed, finish = jsontap()

for chunk in my_stream:
    feed(chunk)

finish()

result = await root["some_field"]
```

## Error handling

| Situation | Behavior |
|---|---|
| Malformed JSON or source exception | All pending `await`s and `async for` loops receive the exception immediately |
| Key not present in parsed JSON | `KeyError` raised once parsing is complete |
| `.value` accessed before node resolves | `LookupError` |
| `for ... in node` before stream finishes | `RuntimeError` |
| `feed()` called after `finish()` | `RuntimeError` |

## API reference

### `jsontap(source=None)`

| Source type | Behavior | Returns |
|---|---|---|
| Async iterable | Background parsing task starts immediately | `AsyncJsonNode` |
| Sync iterable | Consumed eagerly, values resolved before access | `AsyncJsonNode` |
| None | Manual chunk feeding mode | `(root, feed, finish)` |

### `AsyncJsonNode`

| Pattern | Description |
|---|---|
| `node["key"]` | Get or create a child node |
| `await node` | Block until value is resolved |
| `async for item in node` | Stream array item handles as each slot is parsed |
| `async for value in node.values()` | Stream fully materialized array values |
| `node.value` | Synchronous access to a resolved value |
| `for item in node` | Synchronous iteration over a completed array |
| `node.resolved` | `True` if the node's value has been parsed |
