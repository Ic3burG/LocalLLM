"""Slash-command dispatcher used by the TUI input box."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
    # agent_utils is a bridge-side module that lives at the repo root, not in
    # the localllm package. When `localllm` runs from inside the repo it's
    # importable via sys.path[0]; when run from any other cwd it's not.
    # Degrade gracefully rather than crashing the slash-command path.
    try:
        from agent_utils import TOOL_REGISTRY
    except ModuleNotFoundError:
        return (
            "Tool listing unavailable: agent_utils not on sys.path "
            "(launch `localllm` from the LocalLLM repo root for `/tools`, "
            "or query the bridge directly with `curl http://127.0.0.1:9379/v1/agent/...`)."
        )
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
