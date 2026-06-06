"""Pure completion logic for the TUI input box (no Textual imports)."""

from __future__ import annotations

from localllm.commands import COMMANDS


def slash_candidates(query: str) -> list[tuple[str, str]]:
    """(command, summary) pairs whose command starts with `query`.

    `query` includes the leading slash (e.g. "/mo"); bare "/" returns all.
    """
    return [(name, summary) for name, summary in COMMANDS if name.startswith(query)]
