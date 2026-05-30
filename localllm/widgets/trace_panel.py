"""One-line trace summary: '⚙ N steps · X ms' while a task is running."""

from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static


class TracePanel(Static):
    DEFAULT_CSS = """
    TracePanel {
        height: 1;
        color: $text-muted;
        padding: 0 1;
        dock: bottom;
    }
    """

    steps: reactive[int] = reactive(0)
    elapsed_ms: reactive[int] = reactive(0)
    active: reactive[bool] = reactive(False)

    def watch_steps(self, _: int) -> None:
        self._refresh()

    def watch_elapsed_ms(self, _: int) -> None:
        self._refresh()

    def watch_active(self, _: bool) -> None:
        self._refresh()

    def reset(self) -> None:
        self.steps = 0
        self.elapsed_ms = 0
        self.active = False

    def _refresh(self) -> None:
        if not self.active and self.steps == 0:
            self.update("")
            return
        plural = "s" if self.steps != 1 else ""
        self.update(f"⚙ {self.steps} step{plural} · {self.elapsed_ms} ms")
