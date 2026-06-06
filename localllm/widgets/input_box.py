"""Single-line input with up/down history and @/ completion menu."""

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import Input

from localllm.completions import (
    apply_completion,
    fuzzy_find_files,
    parse_trigger,
    slash_candidates,
)
from localllm.widgets.completion_menu import CompletionMenu


class InputBox(Input):
    BINDINGS = [
        Binding("up", "history_prev", "Prev", show=False),
        Binding("down", "history_next", "Next", show=False),
    ]

    def __init__(self, cwd: str = ".", **kwargs) -> None:
        super().__init__(placeholder="› type a message, /help, or @file", **kwargs)
        self._history: list[str] = []
        self._cursor: int | None = None
        self.cwd = cwd
        self._trigger = None

    # --- history (unchanged behavior) -------------------------------------
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

    # --- completion menu ---------------------------------------------------
    def _menu(self) -> CompletionMenu | None:
        try:
            return self.app.query_one(CompletionMenu)
        except Exception:  # noqa: BLE001  (menu not mounted yet)
            return None

    def update_completions(self) -> None:
        """Recompute the menu from the current text + caret. Called on change."""
        menu = self._menu()
        if menu is None:
            return
        trig = parse_trigger(self.value, self.cursor_position)
        self._trigger = trig
        if trig is None:
            menu.hide()
            return
        if trig.kind == "command":
            items = [
                (name, f"{name}  {summary}")
                for name, summary in slash_candidates(trig.query)
            ]
        else:
            items = [("@" + rel, rel) for rel in fuzzy_find_files(self.cwd, trig.query)]
        if items:
            menu.show(items)
        else:
            menu.hide()

    def apply_value(self, value: str) -> None:
        """Splice the chosen completion into the text."""
        if self._trigger is None:
            return
        text, cursor = apply_completion(self.value, self._trigger, value)
        self.value = text
        self.cursor_position = cursor
        menu = self._menu()
        if menu is not None:
            menu.hide()

    async def on_key(self, event) -> None:
        # Only intercept navigation keys while the menu is open; otherwise let
        # Input's normal bindings (history, submit, focus) run untouched.
        menu = self._menu()
        if menu is None or not menu.display:
            return
        if event.key == "down":
            menu.action_cursor_down()
            event.prevent_default()
            event.stop()
        elif event.key == "up":
            menu.action_cursor_up()
            event.prevent_default()
            event.stop()
        elif event.key in ("enter", "tab"):
            value = menu.current_value()
            if value is not None:
                self.apply_value(value)
            event.prevent_default()
            event.stop()
        elif event.key == "escape":
            menu.hide()
            event.prevent_default()
            event.stop()
