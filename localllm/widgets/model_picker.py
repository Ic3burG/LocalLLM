"""Modal screen for picking a model from a list (↑↓ to move, enter to select)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


class ModelPicker(ModalScreen[str | None]):
    """Returns the chosen model id, or None if cancelled (Esc)."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    ModelPicker {
        align: center middle;
    }
    #card {
        background: $panel;
        border: tall $accent;
        padding: 1 2;
        width: 50;
        height: auto;
    }
    #title { color: $accent; text-style: bold; }
    #hint { color: $text-muted; padding-top: 1; }
    OptionList {
        height: auto;
        max-height: 15;
        background: $panel;
        border: none;
    }
    """

    def __init__(self, models: list[str], current: str) -> None:
        super().__init__()
        self._models = models
        self._current = current

    def _label(self, model: str) -> str:
        if model == self._current:
            return f"● {model}  (current)"
        return f"  {model}"

    def compose(self) -> ComposeResult:
        with Vertical(id="card"):
            yield Static("Select model", id="title")
            yield OptionList(
                *(Option(self._label(m), id=m) for m in self._models),
                id="model-list",
            )
            yield Static("↑↓ move · enter select · esc cancel", id="hint")

    def on_mount(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.focus()
        # Pre-highlight the active model so opening + enter is a no-op switch.
        if self._current in self._models:
            option_list.highlighted = self._models.index(self._current)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)
