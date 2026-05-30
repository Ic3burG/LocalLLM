"""Single-line input with up/down history."""

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Input


class InputBox(Input):
    BINDINGS = [
        Binding("up", "history_prev", "Prev", show=False),
        Binding("down", "history_next", "Next", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(placeholder="› type a message, or /help", **kwargs)
        self._history: list[str] = []
        self._cursor: int | None = None

    def push_history(self, line: str) -> None:
        if line and (not self._history or self._history[-1] != line):
            self._history.append(line)
        self._cursor = None

    def action_history_prev(self) -> None:
        if not self._history:
            return
        self._cursor = (
            len(self._history) - 1 if self._cursor is None else max(0, self._cursor - 1)
        )
        self.value = self._history[self._cursor]

    def action_history_next(self) -> None:
        if self._cursor is None:
            return
        self._cursor += 1
        if self._cursor >= len(self._history):
            self._cursor = None
            self.value = ""
        else:
            self.value = self._history[self._cursor]
