"""Scrolling transcript built on RichLog with markdown rendering."""

from __future__ import annotations

from rich.markdown import Markdown
from rich.text import Text
from textual.widgets import RichLog


class Transcript(RichLog):
    """Read-only scrollback for user prompts, model replies, tool calls."""

    DEFAULT_CSS = """
    Transcript {
        background: $surface;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(wrap=True, markup=True, highlight=False, **kwargs)

    def write_user(self, text: str) -> None:
        self.write(Text("› ", style="bold cyan") + Text(text))

    def write_assistant_chunk(self, chunk: str) -> None:
        self.write(Markdown(chunk))

    def write_tool_call(self, tool: str, args: dict, elapsed_ms: int) -> None:
        args_str = ", ".join(repr(v) for v in args.values())
        self.write(
            Text("⚙ ", style="bold yellow")
            + Text(f"{tool}({args_str})", style="yellow")
            + Text(f"  · {elapsed_ms} ms", style="dim")
        )

    def write_status(self, text: str) -> None:
        self.write(Text(f"… {text}", style="dim italic"))

    def write_error(self, text: str) -> None:
        self.write(Text(f"✗ {text}", style="bold red"))
