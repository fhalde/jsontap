import asyncio
import os

from openai import AsyncOpenAI
from jsontap import jsontap
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

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
HOLD_SECONDS = 3


class TwoPaneUI:
    def __init__(self, console: Console) -> None:
        self._json_buffer = ""
        self._agent_lines: list[str] = []
        self._live: Live | None = None

    def attach_live(self, live: Live) -> None:
        self._live = live

    def append_json(self, chunk: str) -> None:
        self._json_buffer += chunk
        self.refresh()

    def add_agent_line(self, line: str) -> None:
        self._agent_lines.append(line)
        self.refresh()

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=1),
        )

        json_text = Text(
            self._json_buffer or "(waiting for tokens...)",
            no_wrap=False,
            overflow="fold",
        )
        agent_text = Text(
            "\n".join(self._agent_lines) or "(waiting for parsed fields...)",
            no_wrap=False,
            overflow="fold",
        )

        layout["left"].update(
            Panel(json_text, title="Streaming JSON", border_style="cyan")
        )
        layout["right"].update(
            Panel(agent_text, title="Agent Output", border_style="green")
        )
        return layout

    def refresh(self) -> None:
        if self._live is not None:
            self._live.update(self._build_layout(), refresh=True)


async def token_stream(client: AsyncOpenAI, on_chunk=None):
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

    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            if on_chunk is not None:
                on_chunk(delta)
            yield delta


async def main():
    client = AsyncOpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )

    console = Console()
    ui = TwoPaneUI(console)

    with Live(
        ui._build_layout(), console=console, refresh_per_second=12, screen=True
    ) as live:
        ui.attach_live(live)
        ui.add_agent_line("🚀 Starting ticket triage stream...")

        response = jsontap(token_stream(client, on_chunk=ui.append_json))
        ui.add_agent_line("⏳ Waiting for category and urgency...")

        category, urgency = await asyncio.gather(
            response["category"],
            response["urgency"],
        )

        ui.add_agent_line(f"🧭 Routing -> assigned to '{category}'")
        ui.add_agent_line(f"🚨 Urgency -> {urgency.upper()}")

        if urgency in ("high", "critical"):
            ui.add_agent_line("📟 Alert -> paging on-call engineer")

        ui.add_agent_line("🛠️ Action steps:")
        async for step in response["action_steps"]:
            ui.add_agent_line(f"• {await step}")

        full_response = await response["full_response"]
        ui.add_agent_line(f"✅ Final response -> {full_response}")
        ui.add_agent_line("🎉 Done.")
        if HOLD_SECONDS > 0:
            ui.add_agent_line(f"🕒 Closing in {HOLD_SECONDS:g}s...")
            await asyncio.sleep(HOLD_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
