"""Slash-command dispatcher used by the TUI input box."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent_utils import TOOL_REGISTRY

HELP_TEXT = """Slash commands:
  /help              Show this help.
  /model <name>      Switch model (e.g., gemma4-e4b, gemma-31b).
  /clear             Clear the transcript.
  /tools             List available tools (safe vs risky).
  /cwd <path>        Change session cwd (sandbox root).
  /reconnect         Next prompt will retry the bridge probe.
  /quit              Exit the CLI."""


@dataclass(frozen=True)
class CommandResult:
    kind: Literal["show", "set_model", "set_cwd", "clear", "quit"]
    message: str = ""
    value: str = ""


def _tools_text() -> str:
    lines = ["Available tools:"]
    for name in sorted(TOOL_REGISTRY):
        tool = TOOL_REGISTRY[name]
        lines.append(f"  [{tool.risk:5s}] {name:25s} {tool.description}")
    return "\n".join(lines)


def dispatch(line: str, *, model: str) -> CommandResult | None:
    """Return a CommandResult for slash commands, None for plain prompts."""
    if not line.startswith("/"):
        return None
    parts = line.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        return CommandResult(kind="show", message=HELP_TEXT)
    if cmd == "/model":
        if not arg:
            return CommandResult(kind="show", message=f"current model: {model}")
        return CommandResult(kind="set_model", value=arg.strip())
    if cmd == "/clear":
        return CommandResult(kind="clear")
    if cmd == "/tools":
        return CommandResult(kind="show", message=_tools_text())
    if cmd == "/cwd":
        if not arg:
            return CommandResult(kind="show", message="usage: /cwd <path>")
        return CommandResult(kind="set_cwd", value=arg.strip())
    if cmd == "/reconnect":
        return CommandResult(
            kind="show",
            message="reconnect: next prompt will retry the bridge.",
        )
    if cmd == "/quit":
        return CommandResult(kind="quit")
    return CommandResult(kind="show", message=f"unknown command: {cmd}\n\n{HELP_TEXT}")
