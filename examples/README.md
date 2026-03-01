# Examples

`run.py` shows how to use `jsontap` with an OpenRouter streaming response.

It demonstrates progressive JSON consumption:
- route as soon as `category` resolves
- set urgency as soon as `urgency` resolves
- stream `action_steps` as each item arrives
- wait for `full_response` only at the end

## Requirements

- Python 3.12+
- `OPENROUTER_API_KEY` set in your shell

Install dependencies from the project root:

```bash
git clone https://github.com/fhalde/jsontap.git
cd jsontap
uv sync --group example
```

## Run

From the project root:

```bash
export OPENROUTER_API_KEY="<token>"
uv run python examples/run.py
```

## Notes

- The model is configured directly in `examples/run.py`.
- `response_format` is set to `json_schema`, so use a model/provider route that supports it.
- Output quality is only as good as the model you choose.
