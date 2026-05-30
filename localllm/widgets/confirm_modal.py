"""Modal screen for risky-tool approval (Allow / Deny / Esc=Deny)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmModal(ModalScreen[bool]):
    """Returns True for Allow, False for Deny."""

    BINDINGS = [
        Binding("escape", "deny", "Deny"),
        Binding("y", "allow", "Allow"),
        Binding("n", "deny", "Deny"),
    ]

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    #card {
        background: $panel;
        border: tall $warning;
        padding: 1 2;
        width: 70;
        height: auto;
    }
    #title { color: $warning; text-style: bold; }
    #args { color: $text-muted; padding-top: 1; }
    #buttons { padding-top: 1; align-horizontal: right; }
    Button { margin-left: 1; }
    """

    def __init__(self, tool: str, args: dict) -> None:
        super().__init__()
        self._tool = tool
        self._args = args

    def compose(self) -> ComposeResult:
        args_str = ", ".join(repr(v) for v in self._args.values())
        with Vertical(id="card"):
            yield Static(f"⚠  Run risky tool: {self._tool}", id="title")
            yield Static(f"args: ({args_str})", id="args")
            with Horizontal(id="buttons"):
                yield Button("Deny  (n)", variant="default", id="deny-btn")
                yield Button("Allow (y)", variant="warning", id="allow-btn")

    def action_allow(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "allow-btn")
