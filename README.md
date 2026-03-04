# jsontap

**Progressively consume structured output from an LLM as it streams.**

jsontap lets you `await` fields and iterate array item as soon as they appear – without waiting for full JSON completion. Overlap model generation with execution: dispatch tool calls earlier, update interfaces sooner, and cut end-to-end latency.

Built on top of [ijson](https://github.com/ICRAR/ijson), it gives you an awaitable, path-oriented, instant access to your JSON payload so you can write sequential-looking code.

For more details, here's the blog [post](https://fhalde.github.io/posts/jsontap/).

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

jsontap eliminates these workarounds with a clean async API built around an iterative JSON parser [ijson](https://github.com/ICRAR/ijson).

## Sequential code, progressive execution.

With jsontap, you write code that reads top-to-bottom, like you're accessing a fully parsed JSON – except each line resolves as the data arrives:

```python
response = jsontap(chat_completion())

reasoning = await response["reasoning"]
print(f"{reasoning}")

async for call in response["calls"]:
    tool = await call["tool"]
    args = await call["args"]
    asyncio.create_task(dispatch(tool, args))

summary = await response["summary"]
print(f"{summary}")
```

This looks like code you'd write against a fully parsed JSON – but it isn't. Each `await` and `async for` resolves as the corresponding part of the JSON arrives in the stream. `reasoning` unblocks the moment that field is parsed, the `calls` loop starts iterating before the array is complete, and `summary` waits only as long as it needs to.

Here's a showcase of the complete [example](https://github.com/fhalde/jsontap/tree/main/examples)

![jsontap streaming demo](show.gif)

In practice, this means you can add responsiveness to an agent without restructuring your code. If you already have logic that reads from a parsed JSON, the jsontap version looks almost identical.

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
results = await response["results"]
```

Nodes are created lazily and can be subscribed to before their part of the JSON has been parsed. Multiple consumers can `await` or iterate the same node – each gets the full result.

## Limitations

1. String values cannot be iterated at the moment. See [issue](https://github.com/fhalde/jsontap/issues/5).
2. This is not a general-purpose JSON library.
3. There's no support for custom field decoders (e.g., to parse dates).

## Error handling

| Situation | Behavior |
|---|---|
| Malformed JSON or source exception | All pending `await`s and `async for` loops receive the exception immediately |
| Key not present in parsed JSON | `KeyError` raised once parsing is complete |
| `.value` accessed before node resolves | `LookupError` |
| `for ... in node` before stream finishes | `RuntimeError` |
| `feed()` called after `finish()` | `RuntimeError` |

## API reference

### `jsontap(stream) -> AsyncJsonNode`

| Source type | Behavior | Returns |
|---|---|---|
| `AsyncStream[ChatCompletionChunk]` | Background parsing task starts immediately | `AsyncJsonNode` |

### `AsyncJsonNode`

| Pattern | Description |
|---|---|
| `node["key"]` | Get or create a child node |
| `await node` | Block until value is resolved |
| `async for item in node` | Stream array item handles as each slot is parsed |
| `async for value in node.values()` | Stream fully materialized array values |