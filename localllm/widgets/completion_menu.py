"""Floating autocomplete menu for the input box (commands + @files)."""

from __future__ import annotations

from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option


class CompletionMenu(OptionList):
    """Overlay list of candidates. Driven entirely by InputBox; never focused."""

    DEFAULT_CSS = """
    CompletionMenu {
        layer: overlay;
        dock: bottom;
        offset: 0 -4;
        width: 100%;
        height: auto;
        max-height: 10;
        background: $panel;
        border: tall $accent;
        display: none;
    }
    """

    can_focus = False

    class Picked(Message):
        """A candidate was chosen (mouse click)."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._values: list[str] = []

    def show(self, items: list[tuple[str, str]]) -> None:
        """items: (replacement_value, display_label)."""
        self._values = [value for value, _ in items]
        self.clear_options()
        self.add_options([Option(label) for _, label in items])
        if items:
            self.highlighted = 0
        self.display = True

    def hide(self) -> None:
        self._values = []
        self.display = False

    def current_value(self) -> str | None:
        i = self.highlighted
        if i is not None and 0 <= i < len(self._values):
            return self._values[i]
        return None

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if 0 <= event.option_index < len(self._values):
            self.post_message(self.Picked(self._values[event.option_index]))
