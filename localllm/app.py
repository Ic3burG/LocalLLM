"""LocalLLM Textual App — top-level layout and event loop."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

import httpx
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header

from localllm.agent_client import AgentClient
from localllm.control_server import ControlServer
from localllm.events import (
    ConfirmRequestEvent,
    ConfirmResolvedEvent,
    DoneEvent,
    ErrorEvent,
    StatusEvent,
    StepEvent,
    ThinkingEvent,
)
from localllm.registry_client import RegistryClient, make_payload
from localllm.widgets.confirm_modal import ConfirmModal
from localllm.widgets.input_box import InputBox
from localllm.widgets.status_bar import StatusBar
from localllm.widgets.trace_panel import TracePanel
from localllm.widgets.transcript import Transcript

RECONNECT_BACKOFFS_S = (1.0, 2.0, 4.0, 8.0, 15.0)  # ~30s total

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

    def __init__(
        self,
        bridge_url: str,
        model_id: str = "gemma4-e4b",
        model_ready: bool = True,
    ) -> None:
        super().__init__()
        self._client = AgentClient(base_url=bridge_url)
        self._model_id = model_id
        self._model_ready = model_ready
        self._cwd = str(Path(os.getcwd()).resolve())
        self._session_id = f"cli-{uuid.uuid4().hex[:8]}"
        self._control = ControlServer()
        self._registry_client = RegistryClient(base_url=bridge_url)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical():
            yield Transcript(id="transcript")
            yield InputBox(id="input")
        yield TracePanel(id="trace")
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
        if not self._model_ready:
            self.query_one(Transcript).write_status(
                f"Model {self._model_id} isn't loaded yet — it will load on your "
                f"first message (may take a few seconds)."
            )
        self.run_worker(self._startup_register(), exclusive=False)

    async def _startup_register(self) -> None:
        ws_url = await self._control.start()
        payload = make_payload(
            session_id=self._session_id,
            cwd=self._cwd,
            ws_url=ws_url,
            model=self._model_id,
        )
        registered = await self._registry_client.register(payload)
        if registered:
            await self._registry_client.start_heartbeat(self._session_id)

    async def on_unmount(self) -> None:
        await self._registry_client.stop_heartbeat()
        await self._registry_client.deregister(self._session_id)
        await self._control.stop()
        # Release pooled connections held by the long-lived clients.
        await self._registry_client.close()
        await self._client.close()

    async def on_input_submitted(self, event: InputBox.Submitted) -> None:  # type: ignore[name-defined]
        text = event.value.strip()
        if not text:
            return
        transcript = self.query_one(Transcript)
        input_box = self.query_one(InputBox)
        status = self.query_one(StatusBar)

        # Slash commands short-circuit before the bridge round-trip.
        from localllm.commands import dispatch

        result = dispatch(text, model=self._model_id)
        if result is not None:
            input_box.push_history(text)
            input_box.value = ""
            if result.kind == "show":
                transcript.write_status(result.message)
            elif result.kind == "clear":
                transcript.clear()
            elif result.kind == "set_model":
                self._model_id = result.value
                status.model = result.value
                transcript.write_status(f"model → {result.value}")
            elif result.kind == "set_cwd":
                self._cwd = result.value
                status.cwd = result.value
                transcript.write_status(f"cwd → {result.value}")
            elif result.kind == "quit":
                self.exit()
            return

        transcript.write_user(text)
        input_box.push_history(text)
        input_box.value = ""
        status.state = "thinking"
        trace = self.query_one(TracePanel)
        trace.reset()
        trace.active = True

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
                    trace.steps += 1
                    trace.elapsed_ms += ev.elapsed_ms
                elif isinstance(ev, ConfirmRequestEvent):
                    status.state = "waiting"
                    approved = await self.push_screen_wait(
                        ConfirmModal(tool=ev.tool, args=ev.args)
                    )
                    await self._client.confirm(
                        task_id=ev.task_id, approved=bool(approved)
                    )
                    status.state = "thinking"
                elif isinstance(ev, ConfirmResolvedEvent):
                    # Echo of our own decision — no-op
                    pass
                elif isinstance(ev, DoneEvent):
                    transcript.write_assistant_chunk(ev.message)
                elif isinstance(ev, ErrorEvent):
                    transcript.write_error(ev.message)
        except httpx.HTTPError as exc:
            transcript.write_error(f"bridge disconnected ({exc.__class__.__name__})")
            status.state = "waiting"
            transcript.write_status("retrying bridge…")
            ok = await self._wait_for_bridge()
            if ok:
                transcript.write_status(
                    "bridge back. Re-send your last prompt to resume."
                )
            else:
                transcript.write_error(
                    "bridge still down after 30s. Try /reconnect or /quit."
                )
        except Exception as exc:  # noqa: BLE001
            transcript.write_error(f"unexpected: {exc}")
        finally:
            status.state = "ready"
            trace.active = False

    async def _wait_for_bridge(self) -> bool:
        """Probe /v1/health with exp backoff (1→2→4→8→15s; ~30s total)."""
        for delay in RECONNECT_BACKOFFS_S:
            if await self._client.health():
                return True
            await asyncio.sleep(delay)
        return False
