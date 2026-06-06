"""Pure completion logic for the TUI input box (no Textual imports)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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


IGNORE_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "mlx_models",
    ".worktrees",
}

_MAX_ENTRIES = 20_000  # ceiling so a pathological tree can't hang a keystroke


def _is_subsequence(needle: str, haystack: str) -> bool:
    it = iter(haystack)
    return all(ch in it for ch in needle)


def _score(query: str, relpath: str) -> int:
    """Higher is better; negative means "no match" (excluded)."""
    if not query:
        return 0
    path = relpath.lower()
    base = os.path.basename(path)
    if query in base:
        return 1000 - base.index(query)
    if query in path:
        return 500 - min(path.index(query), 499)
    if _is_subsequence(query, path):
        return 100
    return -1


def fuzzy_find_files(root: str | Path, query: str, *, limit: int = 20) -> list[str]:
    """POSIX-relative paths under `root` matching `query`, best first.

    Walks once, pruning IGNORE_DIRS. Empty query returns the shortest paths
    first (stable). Capped at `_MAX_ENTRIES` files scanned.
    """
    root = Path(root)
    q = query.lower()
    scored: list[tuple[int, str]] = []
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for name in filenames:
            count += 1
            if count > _MAX_ENTRIES:
                break
            rel = (Path(dirpath) / name).relative_to(root).as_posix()
            score = _score(q, rel)
            if score >= 0:
                scored.append((score, rel))
        if count > _MAX_ENTRIES:
            break
    # Best score first; ties broken by shorter path then alphabetical.
    scored.sort(key=lambda t: (-t[0], len(t[1]), t[1]))
    return [rel for _, rel in scored[:limit]]
