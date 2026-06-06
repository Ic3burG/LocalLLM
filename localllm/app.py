"""LocalLLM Textual App — top-level layout and event loop."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

import httpx
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input

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
from localllm.mentions import expand_mentions, human_size
from localllm.registry_client import RegistryClient, make_payload
from localllm.widgets.completion_menu import CompletionMenu
from localllm.widgets.confirm_modal import ConfirmModal
from localllm.widgets.input_box import InputBox
from localllm.widgets.model_picker import ModelPicker
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
        layers: base overlay;
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
            yield CompletionMenu(id="completion")
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
        self.query_one(InputBox).cwd = self._cwd
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

    def on_input_changed(self, event: Input.Changed) -> None:
        if isinstance(event.control, InputBox):
            event.control.update_completions()

    def on_completion_menu_picked(self, event: CompletionMenu.Picked) -> None:
        self.query_one(InputBox).apply_value(event.value)

    async def on_input_submitted(self, event: InputBox.Submitted) -> None:  # type: ignore[name-defined]
        text = event.value.strip()
        if not text:
            return
        # Record history + clear the box immediately for responsiveness, then do
        # the real work in a worker. Modal dialogs (model picker, confirm modal)
        # use push_screen_wait, which Textual 8.x only permits inside a worker.
        input_box = self.query_one(InputBox)
        input_box.push_history(text)
        input_box.value = ""
        self._process_submit(text)

    @work(exclusive=True)
    async def _process_submit(self, text: str) -> None:
        """Worker that handles one submitted line (slash command or prompt).

        Runs in a worker so push_screen_wait is legal; any uncaught error is
        logged to the CLI log and surfaced in the transcript rather than
        tearing down the whole TUI."""
        transcript = self.query_one(Transcript)
        status = self.query_one(StatusBar)

        # Slash commands short-circuit before the bridge round-trip.
        from localllm.commands import dispatch

        result = dispatch(text, model=self._model_id)
        if result is not None:
            try:
                await self._handle_command(result, transcript, status)
            except Exception:  # noqa: BLE001
                logger.exception("error handling command: %r", text)
                transcript.write_error(
                    "internal error running command — see ~/.localllm/cli.log"
                )
            return

        exp = expand_mentions(text, self._cwd)
        transcript.write_user(text)
        for rel, n in exp.attached:
            transcript.write_status(f"📎 attached: {rel} ({human_size(n)})")
        for warning in exp.warnings:
            transcript.write_error(warning)
        status.state = "thinking"
        trace = self.query_one(TracePanel)
        trace.reset()
        trace.active = True

        try:
            async for ev in self._client.run_and_stream(
                prompt=exp.text,
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
            logger.warning("bridge disconnected during run: %r", exc)
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
        except Exception:  # noqa: BLE001
            logger.exception("unexpected error during agent run: %r", text)
            transcript.write_error("unexpected error — see ~/.localllm/cli.log")
        finally:
            status.state = "ready"
            trace.active = False

    async def _handle_command(self, result, transcript, status) -> None:
        """Apply a parsed slash command. May open modal dialogs."""
        if result.kind == "show":
            transcript.write_status(result.message)
        elif result.kind == "clear":
            transcript.clear()
        elif result.kind == "set_model":
            self._model_id = result.value
            status.model = result.value
            transcript.write_status(f"model → {result.value}")
        elif result.kind == "pick_model":
            models = await self._client.list_models()
            if not models:
                transcript.write_status(
                    "no models available from the bridge "
                    "(use /model <name> to switch directly)."
                )
                return
            chosen = await self.push_screen_wait(
                ModelPicker(models=models, current=self._model_id)
            )
            if chosen and chosen != self._model_id:
                self._model_id = chosen
                status.model = chosen
                transcript.write_status(f"model → {chosen}")
        elif result.kind == "set_cwd":
            self._cwd = result.value
            status.cwd = result.value
            transcript.write_status(f"cwd → {result.value}")
        elif result.kind == "quit":
            self.exit()

    async def _wait_for_bridge(self) -> bool:
        """Probe /v1/health with exp backoff (1→2→4→8→15s; ~30s total)."""
        for delay in RECONNECT_BACKOFFS_S:
            if await self._client.health():
                return True
            await asyncio.sleep(delay)
        return False

    def _handle_exception(self, error: Exception) -> None:
        """Central Textual hook for *every* unhandled exception (any handler,
        worker, or startup task). Log the full traceback to ~/.localllm/cli.log
        before Textual restores the terminal — otherwise the crash is lost. Then
        defer to Textual's default teardown/rendering."""
        logger.critical("unhandled exception — TUI will exit", exc_info=error)
        super()._handle_exception(error)
