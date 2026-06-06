"""Pure completion logic for the TUI input box (no Textual imports)."""

from __future__ import annotations

from dataclasses import dataclass

from localllm.commands import COMMANDS


def slash_candidates(query: str) -> list[tuple[str, str]]:
    """(command, summary) pairs whose command starts with `query`.

    `query` includes the leading slash (e.g. "/mo"); bare "/" returns all.
    """
    return [(name, summary) for name, summary in COMMANDS if name.startswith(query)]


@dataclass(frozen=True)
class Trigger:
    kind: str  # "command" | "file"
    query: str  # command: "/mo" (slash included); file: "ser" (no @)
    start: int  # index where the replaced token begins
    end: int  # index where the replaced token ends (the caret)


def parse_trigger(text: str, cursor: int) -> Trigger | None:
    """Identify an active completion trigger at the caret, or None."""
    cursor = max(0, min(cursor, len(text)))
    before = text[:cursor]
    # Command mode: line starts with "/" and the caret is still in the first
    # token (no whitespace typed yet).
    if text.startswith("/") and not any(c.isspace() for c in before):
        return Trigger(kind="command", query=before, start=0, end=cursor)
    # File mode: the whitespace-delimited token ending at the caret starts "@".
    start = cursor
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    token = text[start:cursor]
    if token.startswith("@"):
        return Trigger(kind="file", query=token[1:], start=start, end=cursor)
    return None


def apply_completion(text: str, trigger: Trigger, replacement: str) -> tuple[str, int]:
    """Splice `replacement` over the trigger span; return (new_text, new_cursor).

    A trailing space is appended so the user can keep typing immediately.
    """
    new_text = text[: trigger.start] + replacement + " " + text[trigger.end :]
    new_cursor = trigger.start + len(replacement) + 1
    return new_text, new_cursor
