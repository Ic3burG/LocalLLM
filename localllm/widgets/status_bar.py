"""Footer status line: model · cwd · session id · state."""

from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $boost;
        color: $text-muted;
        padding: 0 1;
    }
    """

    model: reactive[str] = reactive("gemma4-e4b")
    cwd: reactive[str] = reactive("")
    session_id: reactive[str] = reactive("")
    state: reactive[str] = reactive("ready")  # ready | thinking | tool | waiting

    def watch_model(self, _: str) -> None:
        self._refresh()

    def watch_cwd(self, _: str) -> None:
        self._refresh()

    def watch_session_id(self, _: str) -> None:
        self._refresh()

    def watch_state(self, _: str) -> None:
        self._refresh()

    def _refresh(self) -> None:
        sid = self.session_id[:8] if self.session_id else "—"
        self.update(
            f"[{self.state}]  model: {self.model}"
            f"  ·  cwd: {self.cwd}  ·  session: {sid}"
        )
