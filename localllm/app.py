"""LocalLLM Textual App — top-level layout and event loop."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header

from localllm.agent_client import AgentClient
from localllm.events import (
    DoneEvent,
    ErrorEvent,
    StatusEvent,
    StepEvent,
    ThinkingEvent,
)
from localllm.widgets.input_box import InputBox
from localllm.widgets.status_bar import StatusBar
from localllm.widgets.transcript import Transcript

logger = logging.getLogger(__name__)


class LocalLLMApp(App):
    """The main TUI."""

    TITLE = "LocalLLM"
    BINDINGS = [Binding("ctrl+c", "quit", "Quit", priority=True)]

    CSS = """
    Screen {
        layout: vertical;
    }
    Transcript {
        height: 1fr;
    }
    InputBox {
        height: 3;
        dock: bottom;
        margin-bottom: 1;
    }
    """

    def __init__(self, bridge_url: str, model_id: str = "gemma4-e4b") -> None:
        super().__init__()
        self._client = AgentClient(base_url=bridge_url)
        self._model_id = model_id
        self._cwd = str(Path(os.getcwd()).resolve())
        self._session_id = f"cli-{uuid.uuid4().hex[:8]}"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical():
            yield Transcript(id="transcript")
            yield InputBox(id="input")
        yield StatusBar(id="status")
        yield Footer()

    def on_mount(self) -> None:
        status = self.query_one(StatusBar)
        status.model = self._model_id
        status.cwd = self._cwd
        status.session_id = self._session_id
        status.state = "ready"
        self.query_one(InputBox).focus()
        self.query_one(Transcript).write_status(
            f"Connected. cwd: {self._cwd}  ·  model: {self._model_id}"
        )

    async def on_input_submitted(self, event: InputBox.Submitted) -> None:  # type: ignore[name-defined]
        text = event.value.strip()
        if not text:
            return
        transcript = self.query_one(Transcript)
        input_box = self.query_one(InputBox)
        status = self.query_one(StatusBar)

        transcript.write_user(text)
        input_box.push_history(text)
        input_box.value = ""
        status.state = "thinking"

        try:
            async for ev in self._client.run_and_stream(
                prompt=text,
                model_id=self._model_id,
                cwd=self._cwd,
                cli_session_id=self._session_id,
            ):
                if isinstance(ev, StatusEvent):
                    transcript.write_status(ev.message)
                elif isinstance(ev, ThinkingEvent):
                    transcript.write_status(f"thinking: {ev.content[:120]}")
                elif isinstance(ev, StepEvent):
                    transcript.write_tool_call(ev.tool, ev.args, ev.elapsed_ms)
                elif isinstance(ev, DoneEvent):
                    transcript.write_assistant_chunk(ev.message)
                elif isinstance(ev, ErrorEvent):
                    transcript.write_error(ev.message)
                # Other event types (confirm_*, sources, image) handled in M3+
        except Exception as exc:  # noqa: BLE001
            transcript.write_error(f"bridge error: {exc}")
        finally:
            status.state = "ready"
