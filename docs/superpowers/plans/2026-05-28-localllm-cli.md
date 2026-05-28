# LocalLLM CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Claude-Code-style terminal client (`localllm`) on top of the existing LocalLLM bridge. The CLI is standalone (only depends on the FastAPI bridge), runs a rich Textual TUI scoped to the launch directory, and publishes its existence to a bridge-side registry so the web UI can read-only mirror live CLI sessions.

**Architecture:** CLI is a thin Textual renderer; the ReAct loop stays in `agent.py`. CLI calls existing `/v1/agent/*` endpoints, passes its `cwd` so tools sandbox to it, and POSTs `/v1/cli/register` so the web sidebar can discover it. A new `cli_sessions.py` on the bridge keeps an in-memory session registry with file snapshot and fans out agent events to web subscribers via `/v1/cli/stream/{id}`. Web changes are purely additive (one sidebar section, one mirror view, two server.js routes).

**Tech Stack:** Python 3.10, Textual (`textual>=0.60`), httpx + httpx-sse for SSE client, aiohttp for the in-CLI WS server, FastAPI for new bridge routes, pytest with `asyncio_mode=auto`. Web changes are vanilla JS + Node Express (existing stack).

**Spec:** `docs/superpowers/specs/2026-05-28-localllm-cli-design.md`

**Reading order for new context:** spec §3 architecture diagram → spec §5 bridge protocol → this plan.

---

## Project conventions (apply to every task)

- **Format on save.** Pre-commit hook (`scripts/hooks/pre-commit`) auto-runs `ruff format` and `prettier --write` on staged files. Just commit; the hook handles formatting.
- **Pre-push gate.** Before declaring a milestone done, run `bash .git/hooks/pre-push` and confirm exit 0. This is the CI mirror per `CLAUDE.md`.
- **Test marker.** Python tests added by this plan have no special marker unless noted; they run in default CI. The single Textual TUI smoke test is marked `@pytest.mark.needs_tty` and excluded.
- **Bridge restart.** After editing `gemma_bridge.py`, `agent.py`, `agent_utils.py`, or anything imported by the bridge, restart the launchd service or you will be testing stale code: `launchctl kickstart -k gui/$UID/com.gemini.litert`.
- **No `--no-verify`, no amending pushed commits.** See `CLAUDE.md`.
- **Imports.** New files use existing patterns: top-of-file stdlib → 3p → local; ruff handles sorting.

---

## Files this plan creates or modifies

### New files

| Path                                  | Purpose                                                    |
| ------------------------------------- | ---------------------------------------------------------- |
| `localllm/__init__.py`                | Package marker                                             |
| `localllm/cli.py`                     | Entry point: argparse, bridge health probe, launches `App` |
| `localllm/app.py`                     | Textual `App` subclass: layout, key bindings, lifecycle    |
| `localllm/agent_client.py`            | Async HTTP+SSE client for `/v1/agent/*`                    |
| `localllm/registry_client.py`         | Register / heartbeat / deregister against `/v1/cli/*`      |
| `localllm/control_server.py`          | aiohttp WS server on `127.0.0.1:0`; MVP no-op handler      |
| `localllm/commands.py`                | Slash-command dispatcher                                   |
| `localllm/config.py`                  | `~/.localllm/config.toml` reader; creates dir at 0700      |
| `localllm/events.py`                  | Typed dataclasses for SSE events                           |
| `localllm/widgets/__init__.py`        | Widgets sub-package marker                                 |
| `localllm/widgets/transcript.py`      | `RichLog` transcript                                       |
| `localllm/widgets/input_box.py`       | Multi-line input w/ ↑/↓ history                            |
| `localllm/widgets/status_bar.py`      | Footer: model · cwd · session id · token count             |
| `localllm/widgets/confirm_modal.py`   | `ModalScreen` for risky-tool approval                      |
| `localllm/widgets/trace_panel.py`     | Collapsible tool-call panel                                |
| `cli_sessions.py`                     | Bridge-side registry + fanout + FastAPI router             |
| `tests/test_cli_events.py`            | Unit: SSE event dataclass round-trip                       |
| `tests/test_cli_agent_client.py`      | Unit: agent_client against stub SSE server                 |
| `tests/test_cli_commands.py`          | Unit: slash-command dispatch                               |
| `tests/test_cli_registry_client.py`   | Unit: registry client w/ retry                             |
| `tests/test_cli_sessions_registry.py` | Unit: bridge-side registry behavior                        |
| `tests/test_cli_endpoints.py`         | Integration: `/v1/cli/*` routes via `TestClient`           |
| `tests/test_agent_with_cwd.py`        | Integration: per-session cwd sandbox                       |
| `tests/test_cli_stream_fanout.py`     | Integration: SSE mirror fanout                             |
| `tests/test_tui_smoke.py`             | TUI smoke (marker `needs_tty`, excluded from CI)           |

### Modified files

| Path                   | Change                                                                                                                                  |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `gemma_bridge.py`      | Add `/v1/health` route; mount `cli_sessions.router` at `/v1/cli`; pass-through optional `cwd` field in agent run handler                |
| `agent.py`             | `react_loop_sse` accepts optional `cwd` + `cli_session_id`; sets `current_cwd_var`; calls `cli_sessions.fanout()` after every `q.put()` |
| `agent_utils.py`       | `validate_path` consults `current_cwd_var` for additional allowed root                                                                  |
| `logging_config.py`    | Add `current_cwd_var = ContextVar[str \| None]("current_cwd", default=None)`                                                            |
| `pyproject.toml`       | Add `[project]` table with `name`, `version`, `dependencies`, `[project.scripts] localllm = "localllm.cli:main"`                        |
| `requirements.txt`     | Add `textual>=0.60`, `httpx-sse>=0.4`, `aiohttp>=3.9`                                                                                   |
| `pytest.ini`           | Register `needs_tty` marker; exclude from default collection                                                                            |
| `gemma-web/server.js`  | Two pass-through routes: `GET /v1/cli/sessions`, `GET /v1/cli/stream/:sid` (SSE)                                                        |
| `gemma-web/index.html` | New collapsible "Live CLI Sessions" sidebar section + Mirror View pane                                                                  |

---

## Milestone roadmap

Each milestone ends with a green `bash .git/hooks/pre-push` and is independently shippable.

- **M1.** Bridge `/v1/health` + project package skeleton + `events.py` + `agent_client.py` (with unit tests).
- **M2.** TUI shell: app/transcript/input/status — can chat with the model, see streamed tokens, no tools.
- **M3.** Agent mode parity: confirm modal + bridge-reconnect backoff + trace panel — full ReAct flow with risky-tool confirmations.
- **M4.** Per-session sandbox: `current_cwd_var`, `validate_path` extension, `/v1/agent/run` accepts `cwd`.
- **M5.** Bridge session registry + CLI registry client + no-op control server.
- **M6.** Web mirror: `/v1/cli/stream/{id}` fanout + sidebar section + Mirror View + server.js proxy.
- **M7.** Polish: slash commands (`/model`, `/clear`, `/tools`, `/cwd`), reconnect logic, `~/.localllm/config.toml`, README update.

---

# Milestone 1 — Foundation

End state: `pip install -e .` works, `localllm --version` prints, `/v1/health` returns OK on the bridge, `events.py` and `agent_client.py` have green tests against a stub SSE server.

## Task M1.1 — Add `/v1/health` to the bridge

**Files:**

- Modify: `gemma_bridge.py` (add route near other `@app.get` definitions, e.g. after line 208)
- Create: `tests/test_bridge_health.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bridge_health.py
from fastapi.testclient import TestClient

from gemma_bridge import app


def test_health_returns_ok():
    client = TestClient(app)
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the test and verify it fails**

```
.venv/bin/python -m pytest tests/test_bridge_health.py -v
```

Expected: FAIL with 404 (route not yet defined).

- [ ] **Step 3: Implement**

In `gemma_bridge.py`, find the line that mounts the agent router (`app.include_router(agent_router, prefix="/v1/agent")`, ~line 199) and add directly after it:

```python
@app.get("/v1/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 4: Run the test and verify it passes**

```
.venv/bin/python -m pytest tests/test_bridge_health.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add gemma_bridge.py tests/test_bridge_health.py
git commit -m "feat(bridge): add /v1/health for CLI readiness probe"
```

## Task M1.2 — Create the `localllm/` package skeleton + console script

**Files:**

- Create: `localllm/__init__.py`
- Create: `localllm/cli.py` (stub)
- Modify: `pyproject.toml` (add `[project]` + `[project.scripts]`)
- Modify: `requirements.txt` (add new deps)

- [ ] **Step 1: Inspect current pyproject.toml**

```
cat pyproject.toml
```

Note: it currently only has `[tool.ruff]` blocks. We're going to add `[project]` and `[project.scripts]` while preserving the existing ruff config.

- [ ] **Step 2: Create the package marker and a stub `cli.py`**

```python
# localllm/__init__.py
"""LocalLLM CLI — a Claude-Code-style terminal client."""

__version__ = "0.1.0"
```

```python
# localllm/cli.py
"""Entry point for the `localllm` command."""

from __future__ import annotations

import argparse
import sys

from localllm import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="localllm", description="LocalLLM CLI")
    parser.add_argument(
        "--version", action="version", version=f"localllm {__version__}"
    )
    parser.parse_args(argv)
    print("localllm CLI scaffold — not yet implemented", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Update `pyproject.toml`**

Add at the top of the file (before the existing `[tool.ruff]` block):

```toml
[project]
name = "localllm"
version = "0.1.0"
description = "LocalLLM CLI — a Claude-Code-style terminal client for the LocalLLM bridge"
requires-python = ">=3.10"

[project.scripts]
localllm = "localllm.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["localllm*"]
```

- [ ] **Step 4: Update `requirements.txt`**

Append:

```
textual>=0.60
httpx-sse>=0.4
aiohttp>=3.9
```

- [ ] **Step 5: Install the package + new deps into the venv**

```
.venv/bin/pip install -e .
.venv/bin/pip install textual httpx-sse aiohttp
```

Expected: installation succeeds; `localllm` becomes available on PATH (within the venv).

- [ ] **Step 6: Smoke-test the entry point**

```
.venv/bin/localllm --version
```

Expected: prints `localllm 0.1.0`.

- [ ] **Step 7: Commit**

```bash
git add localllm/__init__.py localllm/cli.py pyproject.toml requirements.txt
git commit -m "feat(cli): add localllm package skeleton and console script entry point"
```

## Task M1.3 — Define SSE event dataclasses (`events.py`) + tests

The bridge emits 8 SSE event shapes (see `agent.py` `react_loop_sse`): `status`, `thinking`, `step`, `confirm_request`, `confirm_resolved`, `done`, `error`, `sources`. Plus `image`. We model them as typed dataclasses to keep the rest of the CLI type-safe.

**Files:**

- Create: `localllm/events.py`
- Create: `tests/test_cli_events.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_events.py
import json

import pytest

from localllm.events import (
    ConfirmRequestEvent,
    ConfirmResolvedEvent,
    DoneEvent,
    ErrorEvent,
    ImageEvent,
    SourcesEvent,
    StatusEvent,
    StepEvent,
    ThinkingEvent,
    parse_event,
)


@pytest.mark.parametrize(
    "raw,expected_type,expected_attrs",
    [
        ({"type": "status", "message": "Loading…"}, StatusEvent, {"message": "Loading…"}),
        (
            {"type": "thinking", "content": "Let me think"},
            ThinkingEvent,
            {"content": "Let me think"},
        ),
        (
            {
                "type": "step",
                "tool": "read_file",
                "args": {"0": "README.md"},
                "result": "hello",
                "elapsed_ms": 42,
            },
            StepEvent,
            {"tool": "read_file", "elapsed_ms": 42},
        ),
        (
            {
                "type": "confirm_request",
                "task_id": "t1",
                "tool": "shell",
                "args": {"0": "ls"},
            },
            ConfirmRequestEvent,
            {"task_id": "t1", "tool": "shell"},
        ),
        (
            {"type": "confirm_resolved", "approved": True},
            ConfirmResolvedEvent,
            {"approved": True},
        ),
        ({"type": "done", "message": "all done"}, DoneEvent, {"message": "all done"}),
        ({"type": "error", "message": "oops"}, ErrorEvent, {"message": "oops"}),
        (
            {"type": "sources", "items": [{"url": "https://x", "kind": "web"}]},
            SourcesEvent,
            {"items": [{"url": "https://x", "kind": "web"}]},
        ),
        (
            {
                "type": "image",
                "image_b64": "AAA",
                "width": 512,
                "height": 512,
                "steps": 4,
                "elapsed_ms": 100,
                "prompt": "cat",
                "size": "512x512",
            },
            ImageEvent,
            {"width": 512, "height": 512},
        ),
    ],
)
def test_parse_event_roundtrip(raw, expected_type, expected_attrs):
    event = parse_event(json.dumps(raw))
    assert isinstance(event, expected_type)
    for key, val in expected_attrs.items():
        assert getattr(event, key) == val


def test_parse_event_unknown_type_returns_none():
    assert parse_event(json.dumps({"type": "mystery"})) is None


def test_parse_event_malformed_json_returns_none():
    assert parse_event("not json") is None
```

- [ ] **Step 2: Run the test and verify it fails**

```
.venv/bin/python -m pytest tests/test_cli_events.py -v
```

Expected: FAIL with `ImportError` on `localllm.events`.

- [ ] **Step 3: Implement `events.py`**

```python
# localllm/events.py
"""Typed dataclasses for SSE events emitted by /v1/agent/stream."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Union

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StatusEvent:
    message: str


@dataclass(frozen=True)
class ThinkingEvent:
    content: str


@dataclass(frozen=True)
class StepEvent:
    tool: str
    args: dict[str, Any]
    result: Any
    elapsed_ms: int


@dataclass(frozen=True)
class ConfirmRequestEvent:
    task_id: str
    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ConfirmResolvedEvent:
    approved: bool


@dataclass(frozen=True)
class DoneEvent:
    message: str


@dataclass(frozen=True)
class ErrorEvent:
    message: str


@dataclass(frozen=True)
class SourcesEvent:
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ImageEvent:
    image_b64: str
    width: int
    height: int
    steps: int
    elapsed_ms: int
    prompt: str
    size: str


Event = Union[
    StatusEvent,
    ThinkingEvent,
    StepEvent,
    ConfirmRequestEvent,
    ConfirmResolvedEvent,
    DoneEvent,
    ErrorEvent,
    SourcesEvent,
    ImageEvent,
]


def parse_event(raw: str) -> Event | None:
    """Parse a raw JSON SSE payload into a typed event, or None if unrecognized."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.debug("malformed event JSON: %r", raw)
        return None
    kind = data.get("type")
    if kind == "status":
        return StatusEvent(message=data.get("message", ""))
    if kind == "thinking":
        return ThinkingEvent(content=data.get("content", ""))
    if kind == "step":
        return StepEvent(
            tool=data.get("tool", ""),
            args=data.get("args") or {},
            result=data.get("result"),
            elapsed_ms=int(data.get("elapsed_ms", 0)),
        )
    if kind == "confirm_request":
        return ConfirmRequestEvent(
            task_id=data.get("task_id", ""),
            tool=data.get("tool", ""),
            args=data.get("args") or {},
        )
    if kind == "confirm_resolved":
        return ConfirmResolvedEvent(approved=bool(data.get("approved")))
    if kind == "done":
        return DoneEvent(message=data.get("message", ""))
    if kind == "error":
        return ErrorEvent(message=data.get("message", ""))
    if kind == "sources":
        return SourcesEvent(items=list(data.get("items") or []))
    if kind == "image":
        return ImageEvent(
            image_b64=data.get("image_b64", ""),
            width=int(data.get("width", 0)),
            height=int(data.get("height", 0)),
            steps=int(data.get("steps", 0)),
            elapsed_ms=int(data.get("elapsed_ms", 0)),
            prompt=data.get("prompt", ""),
            size=data.get("size", ""),
        )
    logger.debug("unknown event type: %r", kind)
    return None
```

- [ ] **Step 4: Run the test and verify it passes**

```
.venv/bin/python -m pytest tests/test_cli_events.py -v
```

Expected: PASS for all 11 parametrized cases + 2 negative tests.

- [ ] **Step 5: Commit**

```bash
git add localllm/events.py tests/test_cli_events.py
git commit -m "feat(cli): typed event dataclasses for /v1/agent SSE stream"
```

## Task M1.4 — `agent_client.py`: async HTTP + SSE client

The client speaks the existing bridge protocol: POST `/v1/agent/run` returns `{task_id}`, then GET `/v1/agent/stream/{task_id}` is an SSE stream. POST `/v1/agent/confirm/{task_id}` resolves a confirmation.

**Files:**

- Create: `localllm/agent_client.py`
- Create: `tests/test_cli_agent_client.py`

- [ ] **Step 1: Write the failing test (uses an in-process FastAPI stub)**

```python
# tests/test_cli_agent_client.py
import asyncio
import json

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from localllm.agent_client import AgentClient
from localllm.events import DoneEvent, StepEvent


def make_stub_app(events: list[dict]) -> FastAPI:
    app = FastAPI()
    state: dict = {}

    @app.post("/v1/agent/run")
    async def run(payload: dict):
        state["last_payload"] = payload
        return {"task_id": "t-123"}

    @app.get("/v1/agent/stream/{task_id}")
    async def stream(task_id: str):
        async def gen():
            for e in events:
                yield f"data: {json.dumps(e)}\n\n"
                await asyncio.sleep(0)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/v1/agent/confirm/{task_id}")
    async def confirm(task_id: str, payload: dict):
        state.setdefault("confirmations", []).append((task_id, payload))
        return {"ok": True}

    app.state.shared = state
    return app


@pytest.fixture
async def stub_server():
    events = [
        {"type": "step", "tool": "read_file", "args": {"0": "README.md"}, "result": "hi", "elapsed_ms": 5},
        {"type": "done", "message": "summary"},
    ]
    app = make_stub_app(events)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    # Wait until a server is up and we know its port
    while not server.started:
        await asyncio.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", app.state.shared
    finally:
        server.should_exit = True
        await task


async def test_run_and_stream_yields_typed_events(stub_server):
    base_url, shared = stub_server
    client = AgentClient(base_url=base_url)
    received: list = []
    async for event in client.run_and_stream(
        prompt="hi", model_id="gemma4-e4b", cwd="/tmp", cli_session_id="cli-1"
    ):
        received.append(event)
    assert any(isinstance(e, StepEvent) and e.tool == "read_file" for e in received)
    assert any(isinstance(e, DoneEvent) for e in received)
    payload = shared["last_payload"]
    assert payload["prompt"] == "hi"
    assert payload["model_id"] == "gemma4-e4b"
    assert payload["cwd"] == "/tmp"
    assert payload["cli_session_id"] == "cli-1"


async def test_confirm_posts_decision(stub_server):
    base_url, shared = stub_server
    client = AgentClient(base_url=base_url)
    await client.confirm(task_id="t-123", approved=True)
    assert shared["confirmations"] == [("t-123", {"approved": True})]
```

- [ ] **Step 2: Run the test and verify it fails**

```
.venv/bin/python -m pytest tests/test_cli_agent_client.py -v
```

Expected: FAIL with `ImportError` on `localllm.agent_client`.

- [ ] **Step 3: Implement `agent_client.py`**

```python
# localllm/agent_client.py
"""Async HTTP + SSE client for the LocalLLM bridge's /v1/agent/* endpoints."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from httpx_sse import aconnect_sse

from localllm.events import Event, parse_event

logger = logging.getLogger(__name__)


class AgentClient:
    """Thin async wrapper over /v1/agent/{run,stream,confirm}."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:9379",
        request_timeout: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = httpx.Timeout(request_timeout, read=None)

    async def run_and_stream(
        self,
        prompt: str,
        model_id: str,
        cwd: str | None = None,
        cli_session_id: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        deep_think: bool = False,
    ) -> AsyncIterator[Event]:
        payload: dict[str, Any] = {"model_id": model_id, "deep_think": deep_think}
        if prompt:
            payload["prompt"] = prompt
        if messages is not None:
            payload["messages"] = messages
        if cwd is not None:
            payload["cwd"] = cwd
        if cli_session_id is not None:
            payload["cli_session_id"] = cli_session_id

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._base}/v1/agent/run", json=payload)
            resp.raise_for_status()
            task_id = resp.json()["task_id"]
            async with aconnect_sse(
                client, "GET", f"{self._base}/v1/agent/stream/{task_id}"
            ) as event_source:
                async for sse in event_source.aiter_sse():
                    if not sse.data:
                        continue
                    event = parse_event(sse.data)
                    if event is None:
                        logger.debug("dropping unrecognized event")
                        continue
                    yield event

    async def confirm(self, task_id: str, approved: bool) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/v1/agent/confirm/{task_id}",
                json={"approved": approved},
            )
            resp.raise_for_status()

    async def health(self) -> bool:
        """Probe /v1/health. Returns True iff status code is 200."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self._base}/v1/health")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False
```

- [ ] **Step 4: Run the test and verify it passes**

```
.venv/bin/python -m pytest tests/test_cli_agent_client.py -v
```

Expected: PASS.

- [ ] **Step 5: Add a health-probe test against the live bridge stub**

Append to `tests/test_cli_agent_client.py`:

```python
async def test_health_returns_true_when_up(stub_server):
    base_url, _ = stub_server
    # The stub doesn't define /v1/health, so confirm health() returns False.
    client = AgentClient(base_url=base_url)
    assert await client.health() is False
```

(We'll add an "up" assertion in M5 once we have a stub that mounts the real bridge.)

- [ ] **Step 6: Run the test and verify it passes**

```
.venv/bin/python -m pytest tests/test_cli_agent_client.py -v
```

Expected: PASS.

- [ ] **Step 7: Run the full pre-push gate to close out M1**

```
bash .git/hooks/pre-push
```

Expected: exit 0.

- [ ] **Step 8: Commit**

```bash
git add localllm/agent_client.py tests/test_cli_agent_client.py
git commit -m "feat(cli): async HTTP+SSE client for /v1/agent endpoints"
```

---

# Milestone 2 — TUI shell (chat with streamed tokens, no tools)

End state: `localllm` launches a Textual app with a transcript + input box + status bar; you can type a prompt, see the model's response stream in, and use Ctrl+C to quit. **Agent mode (tools) intentionally not wired here** — that's M3.

## Task M2.1 — Wire `cli.py` to probe the bridge and exit cleanly when down

**Files:**

- Modify: `localllm/cli.py`
- Create: `tests/test_cli_entry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_entry.py
import asyncio
from unittest.mock import patch

from localllm.cli import _bridge_is_up, main


def test_main_exits_2_when_bridge_down(capsys):
    async def _fake_health():
        return False

    with patch("localllm.cli._bridge_is_up", side_effect=lambda *_: _fake_health()):
        code = main(["--no-tui"])
    assert code == 2
    err = capsys.readouterr().err
    assert "Bridge unreachable" in err
    assert "launchctl kickstart" in err


def test_bridge_is_up_returns_bool():
    async def _runner():
        return await _bridge_is_up("http://127.0.0.1:1")  # nothing listening

    assert asyncio.run(_runner()) is False
```

- [ ] **Step 2: Run the test and verify it fails**

```
.venv/bin/python -m pytest tests/test_cli_entry.py -v
```

Expected: FAIL — `_bridge_is_up` and `--no-tui` not implemented.

- [ ] **Step 3: Update `localllm/cli.py`**

```python
# localllm/cli.py
"""Entry point for the `localllm` command."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from localllm import __version__
from localllm.agent_client import AgentClient


DEFAULT_BRIDGE_URL = "http://127.0.0.1:9379"


async def _bridge_is_up(base_url: str) -> bool:
    return await AgentClient(base_url=base_url).health()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="localllm", description="LocalLLM CLI")
    parser.add_argument("--version", action="version", version=f"localllm {__version__}")
    parser.add_argument(
        "--bridge-url",
        default=os.environ.get("LOCALLLM_BRIDGE_URL", DEFAULT_BRIDGE_URL),
        help="Bridge base URL (default: http://127.0.0.1:9379)",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Probe bridge health and exit (no TUI launch). For tests and CI.",
    )
    args = parser.parse_args(argv)

    if not sys.stdout.isatty() and not args.no_tui:
        print("localllm requires a TTY (no rich-TUI fallback in v1).", file=sys.stderr)
        return 3

    up = asyncio.run(_bridge_is_up(args.bridge_url))
    if not up:
        print(
            f"Bridge unreachable at {args.bridge_url}.\n"
            f"Start it with: launchctl kickstart -k gui/$UID/com.gemini.litert",
            file=sys.stderr,
        )
        return 2

    if args.no_tui:
        print(f"Bridge OK at {args.bridge_url}")
        return 0

    # Import here so tests can run without Textual installed/initialized
    from localllm.app import LocalLLMApp

    app = LocalLLMApp(bridge_url=args.bridge_url)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test and verify it passes**

```
.venv/bin/python -m pytest tests/test_cli_entry.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add localllm/cli.py tests/test_cli_entry.py
git commit -m "feat(cli): bridge health probe, --no-tui flag, cleaner failure modes"
```

## Task M2.2 — Add the three core widgets (skeletons)

These widgets are mostly Textual boilerplate. We test them at the _behavior_ level (the `App.run_test()` harness in M2.4) rather than unit-testing each widget — Textual widgets are too coupled to the framework for meaningful isolation.

**Files:**

- Create: `localllm/widgets/__init__.py`
- Create: `localllm/widgets/transcript.py`
- Create: `localllm/widgets/input_box.py`
- Create: `localllm/widgets/status_bar.py`

- [ ] **Step 1: Create the widgets package marker**

```python
# localllm/widgets/__init__.py
"""Textual widgets for the LocalLLM CLI."""
```

- [ ] **Step 2: Create the transcript widget**

```python
# localllm/widgets/transcript.py
"""Scrolling transcript built on RichLog with markdown rendering."""

from __future__ import annotations

from rich.markdown import Markdown
from rich.text import Text
from textual.widgets import RichLog


class Transcript(RichLog):
    """Read-only scrollback for user prompts, model replies, tool calls."""

    DEFAULT_CSS = """
    Transcript {
        background: $surface;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(wrap=True, markup=True, highlight=False, **kwargs)

    def write_user(self, text: str) -> None:
        self.write(Text("› ", style="bold cyan") + Text(text))

    def write_assistant_chunk(self, chunk: str) -> None:
        # Streaming: append without a newline by re-rendering the trailing line.
        # MVP shortcut: render full chunks as markdown blocks; granular token
        # streaming is improved in M3 once we settle on token vs message events.
        self.write(Markdown(chunk))

    def write_tool_call(self, tool: str, args: dict, elapsed_ms: int) -> None:
        args_str = ", ".join(repr(v) for v in args.values())
        self.write(
            Text("⚙ ", style="bold yellow")
            + Text(f"{tool}({args_str})", style="yellow")
            + Text(f"  · {elapsed_ms} ms", style="dim")
        )

    def write_status(self, text: str) -> None:
        self.write(Text(f"… {text}", style="dim italic"))

    def write_error(self, text: str) -> None:
        self.write(Text(f"✗ {text}", style="bold red"))
```

- [ ] **Step 3: Create the input box widget**

```python
# localllm/widgets/input_box.py
"""Single-line input with up/down history. Multi-line is M7 polish."""

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
            len(self._history) - 1
            if self._cursor is None
            else max(0, self._cursor - 1)
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
```

- [ ] **Step 4: Create the status bar widget**

```python
# localllm/widgets/status_bar.py
"""Footer status line: model · cwd · session id · token count."""

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
            f"[{self.state}]  model: {self.model}  ·  cwd: {self.cwd}  ·  session: {sid}"
        )
```

- [ ] **Step 5: Commit**

```bash
git add localllm/widgets/
git commit -m "feat(cli): transcript, input-box, status-bar widgets"
```

## Task M2.3 — Wire the Textual `App` and connect to the bridge

**Files:**

- Create: `localllm/app.py`

- [ ] **Step 1: Implement `app.py`**

```python
# localllm/app.py
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
                # Other event types are ignored for M2; M3 wires confirmations.
        except Exception as exc:  # noqa: BLE001
            transcript.write_error(f"bridge error: {exc}")
        finally:
            status.state = "ready"
```

- [ ] **Step 2: Smoke-test by launching in a terminal**

In a real terminal (not the agent harness), run:

```
.venv/bin/localllm
```

Expected: Textual TUI opens; status bar shows the cwd and a `cli-…` session id; typing "hi" and pressing Enter streams a model response into the transcript. Ctrl+C exits.

If the bridge isn't running, you'll see the `Bridge unreachable` message from M2.1 instead.

- [ ] **Step 3: Commit**

```bash
git add localllm/app.py
git commit -m "feat(cli): textual app that streams model output to the transcript"
```

## Task M2.4 — Add a `needs_tty` Textual smoke test (excluded from CI)

**Files:**

- Modify: `pytest.ini`
- Create: `tests/test_tui_smoke.py`

- [ ] **Step 1: Update `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
pythonpath = .
markers =
    needs_gpu: tests that require an MLX-capable GPU
    needs_tty: tests that require an interactive TTY (Textual)
addopts = -m "not needs_tty"
```

- [ ] **Step 2: Write the TUI smoke test**

```python
# tests/test_tui_smoke.py
import pytest

from localllm.app import LocalLLMApp
from localllm.widgets.status_bar import StatusBar
from localllm.widgets.transcript import Transcript

pytestmark = pytest.mark.needs_tty


async def test_app_mounts_and_status_populates():
    app = LocalLLMApp(bridge_url="http://127.0.0.1:9999")  # bridge unused here
    async with app.run_test() as pilot:
        await pilot.pause()
        status = app.query_one(StatusBar)
        assert status.cwd
        assert status.session_id.startswith("cli-")
        transcript = app.query_one(Transcript)
        assert transcript is not None
```

- [ ] **Step 3: Verify it is excluded from default pytest run**

```
.venv/bin/python -m pytest tests/test_tui_smoke.py -v
```

Expected: collected 1 item, **deselected by marker** (because `addopts = -m "not needs_tty"`).

- [ ] **Step 4: Manually run it once to confirm it works**

```
.venv/bin/python -m pytest tests/test_tui_smoke.py -v -m "needs_tty"
```

Expected: PASS.

- [ ] **Step 5: Run the full pre-push gate to close out M2**

```
bash .git/hooks/pre-push
```

Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add pytest.ini tests/test_tui_smoke.py
git commit -m "test(cli): TUI smoke test gated behind needs_tty marker"
```

---

# Milestone 3 — Agent mode parity (confirm modal + trace panel)

End state: when the model emits a risky tool, a modal appears in the TUI. Allow/Deny dispatches the same `/v1/agent/confirm/{task_id}` the web uses. Safe tool calls render as compact cards.

## Task M3.1 — Confirm modal widget

**Files:**

- Create: `localllm/widgets/confirm_modal.py`

- [ ] **Step 1: Implement**

```python
# localllm/widgets/confirm_modal.py
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
```

- [ ] **Step 2: Commit**

```bash
git add localllm/widgets/confirm_modal.py
git commit -m "feat(cli): risky-tool confirmation modal"
```

## Task M3.2 — Wire the modal into `app.py`'s event loop

**Files:**

- Modify: `localllm/app.py`

- [ ] **Step 1: Update the event-handling branch in `app.py`**

Replace the body of `on_input_submitted` (the `async for ev` loop) with:

```python
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
                elif isinstance(ev, ConfirmRequestEvent):
                    status.state = "waiting"
                    approved = await self.push_screen_wait(
                        ConfirmModal(tool=ev.tool, args=ev.args)
                    )
                    await self._client.confirm(task_id=ev.task_id, approved=bool(approved))
                    status.state = "thinking"
                elif isinstance(ev, ConfirmResolvedEvent):
                    # Already handled above; ignore the echo
                    pass
                elif isinstance(ev, DoneEvent):
                    transcript.write_assistant_chunk(ev.message)
                elif isinstance(ev, ErrorEvent):
                    transcript.write_error(ev.message)
```

Add the new imports at the top of `app.py`:

```python
from localllm.events import (
    ConfirmRequestEvent,
    ConfirmResolvedEvent,
    DoneEvent,
    ErrorEvent,
    StatusEvent,
    StepEvent,
    ThinkingEvent,
)
from localllm.widgets.confirm_modal import ConfirmModal
```

- [ ] **Step 2: Smoke-test manually**

```
.venv/bin/localllm
```

Then type: `run ls in the current directory` — model should emit a `shell` tool call; modal should appear; Allow runs it; Deny refuses. Esc = Deny.

- [ ] **Step 3: Commit**

```bash
git add localllm/app.py
git commit -m "feat(cli): wire confirmation modal into agent event loop"
```

## Task M3.2b — Bridge reconnect on mid-task disconnect

Spec §7 requires exp. backoff `1→2→4→8 s` for up to 30 s on `httpx.HTTPError`
mid-stream. This is most cleanly expressed as a wrapper that re-issues the
SSE stream — but doing it correctly requires resuming the agent task, which
the existing bridge protocol doesn't support (each `POST /v1/agent/run`
starts a fresh `task_id`). For MVP we implement the simpler, honest version:
on disconnect, surface a clear status, retry the **probe** (so the user can
see when the bridge is back up), and require the user to re-send the prompt.

**Files:**

- Modify: `localllm/app.py`

- [ ] **Step 1: Add a small retry helper in `app.py`**

```python
import httpx

RECONNECT_BACKOFFS_S = (1.0, 2.0, 4.0, 8.0, 15.0)  # ~30s total

async def _wait_for_bridge(client: AgentClient) -> bool:
    for delay in RECONNECT_BACKOFFS_S:
        if await client.health():
            return True
        await asyncio.sleep(delay)
    return False
```

(Add `import asyncio` near the top if not already present.)

- [ ] **Step 2: Update the mid-task exception handler**

Replace the `except Exception as exc:` block in `on_input_submitted` with:

```python
        except httpx.HTTPError as exc:
            transcript.write_error(f"bridge disconnected ({exc.__class__.__name__})")
            status.state = "waiting"
            transcript.write_status("retrying bridge…")
            ok = await _wait_for_bridge(self._client)
            if ok:
                transcript.write_status("bridge back. Re-send your last prompt to resume.")
            else:
                transcript.write_error("bridge still down after 30s. Try /reconnect or /quit.")
        except Exception as exc:  # noqa: BLE001
            transcript.write_error(f"unexpected: {exc}")
```

(Add `import httpx` near the top of `app.py` if not already present.)

- [ ] **Step 3: Commit**

```bash
git add localllm/app.py
git commit -m "feat(cli): exp-backoff probe on bridge disconnect with clear UX"
```

## Task M3.3 — Trace panel placeholder (collapsible tool-call summary)

The trace panel for MVP can be a simple Static line above the input that shows "⚙ N steps · X ms" when a task is running and clears when DONE. The fuller collapsible variant is M7 polish.

**Files:**

- Create: `localllm/widgets/trace_panel.py`
- Modify: `localllm/app.py`

- [ ] **Step 1: Implement the panel**

```python
# localllm/widgets/trace_panel.py
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
        self.update(f"⚙ {self.steps} step{'s' if self.steps != 1 else ''} · {self.elapsed_ms} ms")
```

- [ ] **Step 2: Mount it in `app.py`'s `compose` and update it on each `StepEvent`**

In `app.py` `compose()`, add `yield TracePanel(id="trace")` after `InputBox`. Add import: `from localllm.widgets.trace_panel import TracePanel`.

In `on_input_submitted`, before the `async for` loop:

```python
        trace = self.query_one(TracePanel)
        trace.reset()
        trace.active = True
```

Inside the `StepEvent` branch, also:

```python
                    trace.steps += 1
                    trace.elapsed_ms += ev.elapsed_ms
```

In the `finally:` block:

```python
            trace.active = False
```

- [ ] **Step 3: Run the full pre-push gate to close out M3**

```
bash .git/hooks/pre-push
```

Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add localllm/widgets/trace_panel.py localllm/app.py
git commit -m "feat(cli): live trace panel — step count and cumulative tool time"
```

---

# Milestone 4 — Per-session sandbox (CLI cwd)

End state: when the CLI POSTs `/v1/agent/run` with `cwd=/path/to/foo`, tool calls like `read_file("README.md")` resolve under that directory rather than the bridge's cwd. Web UI calls (no `cwd` field) keep their current behavior.

## Task M4.1 — Add `current_cwd_var` ContextVar in `logging_config.py`

**Files:**

- Modify: `logging_config.py`

- [ ] **Step 1: Inspect current contents**

```
grep -n "ContextVar\|task_id_var" logging_config.py
```

- [ ] **Step 2: Add the new ContextVar near `task_id_var`**

In `logging_config.py`, alongside the existing `task_id_var = ContextVar(...)` line:

```python
current_cwd_var: ContextVar[str | None] = ContextVar("current_cwd", default=None)
```

- [ ] **Step 3: Commit**

```bash
git add logging_config.py
git commit -m "feat(bridge): add current_cwd ContextVar for per-task sandbox"
```

## Task M4.2 — Extend `validate_path` to allow the per-task cwd

**Files:**

- Modify: `agent_utils.py` (function at line 129)
- Create: `tests/test_agent_with_cwd.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/test_agent_with_cwd.py
import os
from pathlib import Path

import pytest

from agent_utils import validate_path
from logging_config import current_cwd_var


def test_validate_path_allows_paths_under_current_cwd_var(tmp_path: Path):
    (tmp_path / "hello.txt").write_text("hi")
    token = current_cwd_var.set(str(tmp_path))
    try:
        resolved = validate_path("hello.txt")
        assert resolved == tmp_path / "hello.txt"
    finally:
        current_cwd_var.reset(token)


def test_validate_path_still_rejects_outside_both(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    token = current_cwd_var.set(str(tmp_path))
    outside = "/etc/passwd"
    try:
        with pytest.raises(PermissionError):
            validate_path(outside)
    finally:
        current_cwd_var.reset(token)


def test_validate_path_falls_back_to_cwd_when_var_unset(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "x.txt").write_text("hi")
    assert validate_path("x.txt") == tmp_path / "x.txt"


def test_validate_path_absolute_in_session_cwd(tmp_path: Path):
    sub = tmp_path / "proj"
    sub.mkdir()
    (sub / "README.md").write_text("hello")
    token = current_cwd_var.set(str(sub))
    try:
        # Absolute path inside the session cwd should resolve
        assert validate_path(str(sub / "README.md")) == sub / "README.md"
    finally:
        current_cwd_var.reset(token)
```

- [ ] **Step 2: Run and verify the first three fail**

```
.venv/bin/python -m pytest tests/test_agent_with_cwd.py -v
```

Expected: the cwd-var tests fail; the fallback test may pass already.

- [ ] **Step 3: Modify `validate_path` in `agent_utils.py` (line 129)**

Replace the existing function body with:

```python
def validate_path(path_str: str, must_exist: bool = True) -> Path:
    from logging_config import current_cwd_var  # local import: avoid cycle at import time

    process_base = Path(os.getcwd()).resolve()
    session_cwd = current_cwd_var.get()
    extra_base: Path | None = Path(session_cwd).resolve() if session_cwd else None
    target = Path(os.path.expanduser(path_str)).resolve()

    allowed_bases: list[Path] = [process_base]
    if extra_base is not None:
        allowed_bases.append(extra_base)

    for base in allowed_bases:
        try:
            target.relative_to(base)
            break
        except ValueError:
            continue
    else:
        raise PermissionError(f"Access denied: {path_str} is outside the sandbox.")

    if must_exist and not target.exists():
        raise FileNotFoundError(f"File not found: {path_str}")

    return target
```

- [ ] **Step 4: Run the tests and verify they pass**

```
.venv/bin/python -m pytest tests/test_agent_with_cwd.py -v
```

Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_utils.py tests/test_agent_with_cwd.py
git commit -m "feat(bridge): per-session cwd extends validate_path allowlist"
```

## Task M4.3 — Thread `cwd` through `/v1/agent/run` → `react_loop_sse`

**Files:**

- Modify: `agent.py` (around line 708 `AgentRequest`, line 730 `run_agent`, line 427 `react_loop_sse`)

- [ ] **Step 1: Extend `AgentRequest` (agent.py:708)**

```python
class AgentRequest(BaseModel):
    prompt: str | None = None
    messages: list[dict] | None = None
    model_id: str = "gemma4-e4b"
    deep_think: bool = False
    cli_session_id: str | None = None
    cwd: str | None = None
```

- [ ] **Step 2: Pass them through in `run_agent` (agent.py:730)**

```python
@router.post("/run")
async def run_agent(req: AgentRequest):
    task_id = str(uuid.uuid4())
    sse_queues[task_id] = asyncio.Queue()
    confirm_queues[task_id] = asyncio.Queue()

    messages = req.messages or []
    if req.prompt:
        messages.append({"role": "user", "content": req.prompt})

    asyncio.create_task(
        react_loop_sse(
            task_id,
            messages,
            req.model_id,
            deep_think=req.deep_think,
            cwd=req.cwd,
            cli_session_id=req.cli_session_id,
        )
    )
    return {"task_id": task_id}
```

- [ ] **Step 3: Update `react_loop_sse` signature and set the ContextVar (agent.py:427)**

Update the signature:

```python
async def react_loop_sse(
    task_id: str,
    messages: list,
    model_id: str,
    deep_think: bool = False,
    cwd: str | None = None,
    cli_session_id: str | None = None,
) -> None:
```

Inside the function, right after `task_id_var.set(task_id)`, add:

```python
    from logging_config import current_cwd_var

    cwd_token = current_cwd_var.set(cwd) if cwd else None
```

In the `finally:` block of the function (currently ends with `await q.put(None)`), insert before `await q.put(None)`:

```python
        if cwd_token is not None:
            current_cwd_var.reset(cwd_token)
```

- [ ] **Step 4: Write an end-to-end integration test**

Append to `tests/test_agent_with_cwd.py`:

```python
# --- end-to-end via the FastAPI bridge -----------------------------------

import asyncio
import json

from fastapi.testclient import TestClient

from agent_utils import register_tool

from gemma_bridge import app


def _drain_stream(client: TestClient, task_id: str, timeout: float = 5.0) -> list[dict]:
    events: list[dict] = []
    with client.stream("GET", f"/v1/agent/stream/{task_id}", timeout=timeout) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                payload = line[len("data: "):]
                events.append(json.loads(payload))
                if events[-1].get("type") in ("done", "error"):
                    break
    return events


async def _fake_react_with_one_step(task_id, messages, model_id, deep_think=False, cwd=None, cli_session_id=None):
    from logging_config import current_cwd_var
    from agent import sse_queues

    q = sse_queues[task_id]
    token = current_cwd_var.set(cwd) if cwd else None
    try:
        from agent_utils import TOOL_REGISTRY
        tool = TOOL_REGISTRY["read_file"]
        try:
            content = await tool.fn("hello.txt")
        except Exception as exc:  # noqa: BLE001
            content = f"ERROR: {exc}"
        await q.put(json.dumps({"type": "step", "tool": "read_file", "args": {"0": "hello.txt"}, "result": content, "elapsed_ms": 1}))
        await q.put(json.dumps({"type": "done", "message": "ok"}))
    finally:
        if token is not None:
            current_cwd_var.reset(token)
        await q.put(None)


def test_agent_run_with_cwd_sandboxes_tools(monkeypatch, tmp_path):
    # Point the model at our fake loop so we don't need MLX.
    (tmp_path / "hello.txt").write_text("from-session-cwd")
    monkeypatch.setattr("agent.react_loop_sse", _fake_react_with_one_step)

    client = TestClient(app)
    resp = client.post(
        "/v1/agent/run",
        json={"prompt": "read hello", "model_id": "gemma4-e4b", "cwd": str(tmp_path), "cli_session_id": "cli-1"},
    )
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    events = _drain_stream(client, task_id)
    step = next(e for e in events if e["type"] == "step")
    assert step["tool"] == "read_file"
    assert step["result"] == "from-session-cwd"
```

- [ ] **Step 5: Run the integration test and verify it passes**

```
.venv/bin/python -m pytest tests/test_agent_with_cwd.py -v
```

Expected: all tests (incl. the e2e) PASS.

- [ ] **Step 6: Run the full pre-push gate to close out M4**

```
bash .git/hooks/pre-push
```

Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add agent.py tests/test_agent_with_cwd.py
git commit -m "feat(bridge): /v1/agent/run accepts cwd + cli_session_id; threads to validate_path"
```

---

# Milestone 5 — Bridge session registry + CLI registry client

End state: `curl http://127.0.0.1:9379/v1/cli/sessions` returns a list of running CLIs. `localllm` registers on startup, heartbeats every 10 s, deregisters on graceful exit. A no-op WS server is bound.

## Task M5.1 — Implement `cli_sessions.py` (registry, fanout, FastAPI routes)

**Files:**

- Create: `cli_sessions.py`
- Create: `tests/test_cli_sessions_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_sessions_registry.py
import asyncio
import json
import time
from pathlib import Path

import pytest

from cli_sessions import (
    HEARTBEAT_STALE_AFTER_S,
    SessionInfo,
    SessionRegistry,
)


def _info(sid: str, cwd: str = "/tmp") -> SessionInfo:
    return SessionInfo(
        session_id=sid,
        pid=1,
        cwd=cwd,
        ws_url="ws://127.0.0.1:1/control",
        model="gemma4-e4b",
        started_at="2026-05-28T00:00:00Z",
        tty="ttys000",
        host="test",
    )


def test_register_and_list(tmp_path: Path):
    reg = SessionRegistry(snapshot_path=tmp_path / "sessions.json")
    reg.register(_info("cli-1"))
    reg.register(_info("cli-2"))
    listed = reg.list()
    assert {s.session_id for s in listed} == {"cli-1", "cli-2"}


def test_heartbeat_resets_staleness(tmp_path: Path, monkeypatch):
    reg = SessionRegistry(snapshot_path=tmp_path / "sessions.json")
    reg.register(_info("cli-1"))
    # Simulate 31 s of inactivity
    reg._last_seen["cli-1"] = time.monotonic() - (HEARTBEAT_STALE_AFTER_S + 1)
    assert reg.list() == []
    reg.heartbeat("cli-1")
    assert [s.session_id for s in reg.list()] == ["cli-1"]


def test_deregister(tmp_path: Path):
    reg = SessionRegistry(snapshot_path=tmp_path / "sessions.json")
    reg.register(_info("cli-1"))
    reg.deregister("cli-1")
    assert reg.list() == []


def test_snapshot_roundtrip(tmp_path: Path):
    path = tmp_path / "sessions.json"
    reg = SessionRegistry(snapshot_path=path)
    reg.register(_info("cli-1", cwd="/foo"))
    raw = json.loads(path.read_text())
    assert raw["cli-1"]["cwd"] == "/foo"

    reg2 = SessionRegistry(snapshot_path=path)
    reg2.load_snapshot()
    # Loaded sessions are stale until heartbeat
    assert reg2.list() == []
    reg2.heartbeat("cli-1")
    assert [s.session_id for s in reg2.list()] == ["cli-1"]


async def test_fanout_delivers_to_all_subscribers(tmp_path: Path):
    reg = SessionRegistry(snapshot_path=tmp_path / "sessions.json")
    reg.register(_info("cli-1"))
    q1 = await reg.subscribe("cli-1")
    q2 = await reg.subscribe("cli-1")
    await reg.fanout("cli-1", {"type": "status", "message": "hi"})
    assert (await asyncio.wait_for(q1.get(), 1)) == {"type": "status", "message": "hi"}
    assert (await asyncio.wait_for(q2.get(), 1)) == {"type": "status", "message": "hi"}


async def test_fanout_to_unknown_session_is_noop(tmp_path: Path):
    reg = SessionRegistry(snapshot_path=tmp_path / "sessions.json")
    await reg.fanout("cli-missing", {"type": "status"})  # must not raise


async def test_fanout_drops_oldest_when_queue_full(tmp_path: Path):
    reg = SessionRegistry(snapshot_path=tmp_path / "sessions.json", max_queue=2)
    reg.register(_info("cli-1"))
    q = await reg.subscribe("cli-1")
    await reg.fanout("cli-1", {"i": 1})
    await reg.fanout("cli-1", {"i": 2})
    await reg.fanout("cli-1", {"i": 3})  # forces drop of {"i":1}
    assert q.qsize() == 2
    assert (await q.get())["i"] == 2
    assert (await q.get())["i"] == 3
```

- [ ] **Step 2: Run the test and verify it fails**

```
.venv/bin/python -m pytest tests/test_cli_sessions_registry.py -v
```

Expected: FAIL — `cli_sessions` module not found.

- [ ] **Step 3: Implement `cli_sessions.py`**

```python
# cli_sessions.py
"""Bridge-side registry of running LocalLLM CLI sessions + SSE fanout."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

HEARTBEAT_STALE_AFTER_S = 30
DEFAULT_SNAPSHOT_PATH = Path.home() / ".localllm" / "sessions.json"


@dataclass
class SessionInfo:
    session_id: str
    pid: int
    cwd: str
    ws_url: str
    model: str
    started_at: str
    tty: str
    host: str


class SessionRegistry:
    """In-memory registry with file-snapshot persistence and SSE fanout."""

    def __init__(self, snapshot_path: Path | None = None, max_queue: int = 1000) -> None:
        self._sessions: dict[str, SessionInfo] = {}
        self._last_seen: dict[str, float] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._snapshot_path = snapshot_path or DEFAULT_SNAPSHOT_PATH
        self._max_queue = max_queue
        self._snapshot_path.parent.mkdir(mode=0o700, exist_ok=True, parents=True)

    # ---- core CRUD --------------------------------------------------------
    def register(self, info: SessionInfo) -> None:
        self._sessions[info.session_id] = info
        self._last_seen[info.session_id] = time.monotonic()
        self._snapshot()

    def heartbeat(self, session_id: str) -> None:
        if session_id not in self._sessions:
            # Loaded-from-snapshot, no live info yet — treat as no-op unless we have one
            return
        self._last_seen[session_id] = time.monotonic()

    def deregister(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._last_seen.pop(session_id, None)
        for q in self._subscribers.pop(session_id, []):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._snapshot()

    def list(self) -> list[SessionInfo]:
        now = time.monotonic()
        live: list[SessionInfo] = []
        for sid, info in list(self._sessions.items()):
            seen = self._last_seen.get(sid, 0)
            if now - seen > HEARTBEAT_STALE_AFTER_S:
                # evict
                self._sessions.pop(sid, None)
                self._last_seen.pop(sid, None)
                continue
            live.append(info)
        return live

    # ---- snapshot persistence --------------------------------------------
    def _snapshot(self) -> None:
        try:
            data = {sid: asdict(info) for sid, info in self._sessions.items()}
            self._snapshot_path.write_text(json.dumps(data, indent=2))
        except OSError as exc:
            logger.warning("registry snapshot failed: %s", exc)

    def load_snapshot(self) -> None:
        if not self._snapshot_path.exists():
            return
        try:
            data = json.loads(self._snapshot_path.read_text())
            self._sessions = {sid: SessionInfo(**raw) for sid, raw in data.items()}
            # Stale until next heartbeat
            self._last_seen = {}
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("registry snapshot load failed: %s", exc)

    # ---- SSE fanout -------------------------------------------------------
    async def subscribe(self, session_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.setdefault(session_id, []).append(q)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(session_id, [])
        if q in subs:
            subs.remove(q)

    async def fanout(self, session_id: str, event: Any) -> None:
        for q in list(self._subscribers.get(session_id, [])):
            if q.full():
                # drop oldest
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.debug("fanout drop after retry: %s", session_id)


# ---------------------------------------------------------------------------
# FastAPI router (mounted at /v1/cli by gemma_bridge.py)
# ---------------------------------------------------------------------------

router = APIRouter()
_registry: SessionRegistry = SessionRegistry()
_registry.load_snapshot()


def get_registry() -> SessionRegistry:
    """Accessor so agent.py can call `get_registry().fanout(...)` lazily."""
    return _registry


class RegisterRequest(BaseModel):
    session_id: str
    pid: int
    cwd: str
    ws_url: str
    model: str
    started_at: str
    tty: str
    host: str


class HeartbeatRequest(BaseModel):
    session_id: str


@router.post("/register")
def register(req: RegisterRequest):
    _registry.register(SessionInfo(**req.model_dump()))
    return {"ok": True}


@router.post("/heartbeat")
def heartbeat(req: HeartbeatRequest):
    _registry.heartbeat(req.session_id)
    return {"ok": True}


@router.delete("/sessions/{session_id}")
def deregister(session_id: str):
    _registry.deregister(session_id)
    return {"ok": True}


@router.get("/sessions")
def list_sessions():
    return [asdict(s) for s in _registry.list()]


@router.get("/stream/{session_id}")
async def stream_session(session_id: str):
    if not any(s.session_id == session_id for s in _registry.list()):
        raise HTTPException(status_code=404, detail="Session not found")
    q = await _registry.subscribe(session_id)

    async def event_gen():
        try:
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            _registry.unsubscribe(session_id, q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run the registry tests and verify they pass**

```
.venv/bin/python -m pytest tests/test_cli_sessions_registry.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add cli_sessions.py tests/test_cli_sessions_registry.py
git commit -m "feat(bridge): CLI session registry with heartbeat, snapshot, and SSE fanout"
```

## Task M5.2 — Mount the `cli_sessions` router on the bridge

**Files:**

- Modify: `gemma_bridge.py`
- Create: `tests/test_cli_endpoints.py`

- [ ] **Step 1: Add the import + mount in `gemma_bridge.py`**

Near the other router mount (line 199):

```python
from cli_sessions import router as cli_sessions_router

# … existing app.include_router(agent_router, prefix="/v1/agent") …
app.include_router(cli_sessions_router, prefix="/v1/cli")
```

- [ ] **Step 2: Write the integration test**

```python
# tests/test_cli_endpoints.py
import time

import cli_sessions
from fastapi.testclient import TestClient

from gemma_bridge import app


def _payload(sid="cli-test"):
    return {
        "session_id": sid,
        "pid": 1,
        "cwd": "/tmp",
        "ws_url": "ws://127.0.0.1:1/control",
        "model": "gemma4-e4b",
        "started_at": "2026-05-28T00:00:00Z",
        "tty": "ttys000",
        "host": "test",
    }


def test_register_list_heartbeat_deregister(monkeypatch, tmp_path):
    # Use an isolated registry so the test doesn't read user state
    fresh = cli_sessions.SessionRegistry(snapshot_path=tmp_path / "sessions.json")
    monkeypatch.setattr(cli_sessions, "_registry", fresh)

    client = TestClient(app)
    assert client.post("/v1/cli/register", json=_payload("cli-1")).status_code == 200
    assert client.post("/v1/cli/register", json=_payload("cli-2")).status_code == 200

    listed = client.get("/v1/cli/sessions").json()
    assert {s["session_id"] for s in listed} == {"cli-1", "cli-2"}

    # Simulate staleness via the registry directly
    fresh._last_seen["cli-1"] = time.monotonic() - 60
    listed = client.get("/v1/cli/sessions").json()
    assert {s["session_id"] for s in listed} == {"cli-2"}

    # Heartbeat re-registers cli-1 (well, requires register first; here we re-register)
    client.post("/v1/cli/register", json=_payload("cli-1"))
    assert client.post("/v1/cli/heartbeat", json={"session_id": "cli-1"}).status_code == 200

    assert client.delete("/v1/cli/sessions/cli-1").status_code == 200
    listed = client.get("/v1/cli/sessions").json()
    assert {s["session_id"] for s in listed} == {"cli-2"}
```

- [ ] **Step 3: Run the test and verify it passes**

```
.venv/bin/python -m pytest tests/test_cli_endpoints.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add gemma_bridge.py tests/test_cli_endpoints.py
git commit -m "feat(bridge): mount /v1/cli router for session registry"
```

## Task M5.3 — CLI `control_server.py` (no-op WS) + `registry_client.py`

**Files:**

- Create: `localllm/control_server.py`
- Create: `localllm/registry_client.py`
- Create: `tests/test_cli_registry_client.py`

- [ ] **Step 1: Implement `control_server.py`**

```python
# localllm/control_server.py
"""Tiny aiohttp WebSocket server bound to 127.0.0.1:0. MVP no-op handler."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiohttp import WSMsgType, web

logger = logging.getLogger(__name__)


class ControlServer:
    def __init__(self) -> None:
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._port: int = 0

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self._port}/control"

    async def start(self) -> str:
        app = web.Application()
        app.router.add_get("/control", self._handler)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await self._site.start()
        # Discover the kernel-assigned port
        servers = self._runner.sites or []
        if servers:
            sock = servers[0]._server.sockets[0]
            self._port = sock.getsockname()[1]
        logger.info("control server up at %s", self.url)
        return self.url

    async def stop(self) -> None:
        if self._runner is not None:
            with suppress(Exception):
                await self._runner.cleanup()

    async def _handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                # MVP: accept-and-discard. v2 will dispatch into the agent loop.
                logger.debug("control msg ignored (v1): %s", msg.data[:200])
            elif msg.type == WSMsgType.ERROR:
                logger.warning("control ws error: %s", ws.exception())
        return ws


async def _self_test() -> None:
    srv = ControlServer()
    await srv.start()
    await asyncio.sleep(0)
    await srv.stop()


if __name__ == "__main__":
    asyncio.run(_self_test())
```

- [ ] **Step 2: Implement `registry_client.py`**

```python
# localllm/registry_client.py
"""Client for the bridge's /v1/cli/{register,heartbeat,sessions} endpoints."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import socket
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


@dataclass
class RegisterPayload:
    session_id: str
    pid: int
    cwd: str
    ws_url: str
    model: str
    started_at: str
    tty: str
    host: str


def make_payload(session_id: str, cwd: str, ws_url: str, model: str) -> RegisterPayload:
    return RegisterPayload(
        session_id=session_id,
        pid=os.getpid(),
        cwd=cwd,
        ws_url=ws_url,
        model=model,
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        tty=os.ttyname(0) if os.isatty(0) else "",
        host=socket.gethostname() or platform.node(),
    )


class RegistryClient:
    def __init__(self, base_url: str = "http://127.0.0.1:9379", retries: int = 3) -> None:
        self._base = base_url.rstrip("/")
        self._retries = retries
        self._heartbeat_task: asyncio.Task | None = None

    async def register(self, payload: RegisterPayload) -> bool:
        for attempt in range(self._retries):
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.post(
                        f"{self._base}/v1/cli/register", json=payload.__dict__
                    )
                    if 200 <= resp.status_code < 300:
                        return True
                    if resp.status_code == 404:
                        logger.warning(
                            "register: bridge has no /v1/cli/register; "
                            "running standalone without web visibility"
                        )
                        return False
                    logger.warning("register failed: %s %s", resp.status_code, resp.text)
            except httpx.HTTPError as exc:
                logger.warning("register attempt %d failed: %s", attempt + 1, exc)
            await asyncio.sleep(1.0)
        return False

    async def heartbeat_once(self, session_id: str) -> bool:
        """3× retry w/ 1 s backoff per spec §7 (Heartbeat blip)."""
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.post(
                        f"{self._base}/v1/cli/heartbeat", json={"session_id": session_id}
                    )
                    if 200 <= resp.status_code < 300:
                        return True
            except httpx.HTTPError as exc:
                logger.debug("heartbeat attempt %d failed: %s", attempt + 1, exc)
            if attempt < 2:
                await asyncio.sleep(1.0)
        return False

    async def start_heartbeat(self, session_id: str, period_s: float = 10.0) -> None:
        async def _loop() -> None:
            while True:
                await asyncio.sleep(period_s)
                await self.heartbeat_once(session_id)

        self._heartbeat_task = asyncio.create_task(_loop())

    async def stop_heartbeat(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task

    async def deregister(self, session_id: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.delete(f"{self._base}/v1/cli/sessions/{session_id}")
        except httpx.HTTPError as exc:
            logger.debug("deregister failed: %s", exc)
```

- [ ] **Step 3: Write tests for the registry client**

```python
# tests/test_cli_registry_client.py
import asyncio
import json

import pytest
import uvicorn
from fastapi import FastAPI, HTTPException

from localllm.registry_client import RegistryClient, make_payload


def make_stub(status_code: int = 200):
    app = FastAPI()
    state: dict = {"calls": []}

    @app.post("/v1/cli/register")
    async def reg(payload: dict):
        state["calls"].append(("register", payload))
        if status_code != 200:
            raise HTTPException(status_code=status_code)
        return {"ok": True}

    @app.post("/v1/cli/heartbeat")
    async def hb(payload: dict):
        state["calls"].append(("heartbeat", payload))
        return {"ok": True}

    @app.delete("/v1/cli/sessions/{sid}")
    async def dereg(sid: str):
        state["calls"].append(("deregister", sid))
        return {"ok": True}

    app.state.shared = state
    return app


@pytest.fixture
async def stub_server():
    apps: list = []

    async def _start(status_code: int = 200):
        app = make_stub(status_code)
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        apps.append((server, task))
        return f"http://127.0.0.1:{port}", app.state.shared

    yield _start

    for server, task in apps:
        server.should_exit = True
        await task


async def test_register_success(stub_server):
    base, shared = await stub_server()
    client = RegistryClient(base_url=base)
    payload = make_payload("cli-1", "/tmp", "ws://127.0.0.1:1/control", "gemma4-e4b")
    ok = await client.register(payload)
    assert ok is True
    assert shared["calls"][0][0] == "register"


async def test_register_404_returns_false(stub_server):
    base, _ = await stub_server(status_code=404)
    client = RegistryClient(base_url=base, retries=1)
    payload = make_payload("cli-1", "/tmp", "ws://127.0.0.1:1/control", "gemma4-e4b")
    ok = await client.register(payload)
    assert ok is False


async def test_heartbeat_and_deregister(stub_server):
    base, shared = await stub_server()
    client = RegistryClient(base_url=base)
    await client.heartbeat_once("cli-1")
    await client.deregister("cli-1")
    kinds = [c[0] for c in shared["calls"]]
    assert "heartbeat" in kinds
    assert "deregister" in kinds


async def test_heartbeat_unreachable_returns_false_quickly(monkeypatch):
    # Patch asyncio.sleep to no-op so the test doesn't wait 2s for the backoffs
    sleeps: list[float] = []

    async def fake_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr("localllm.registry_client.asyncio.sleep", fake_sleep)
    client = RegistryClient(base_url="http://127.0.0.1:1")  # nothing listening
    ok = await client.heartbeat_once("cli-1")
    assert ok is False
    assert sleeps == [1.0, 1.0]  # 3 attempts, 2 sleeps between them
```

- [ ] **Step 4: Run the tests and verify they pass**

```
.venv/bin/python -m pytest tests/test_cli_registry_client.py -v
```

Expected: PASS.

- [ ] **Step 5: Wire the control server + registry client into `app.py`**

In `localllm/app.py`:

```python
# at top
from localllm.control_server import ControlServer
from localllm.registry_client import RegistryClient, make_payload
```

Add to `LocalLLMApp.__init__`:

```python
        self._control = ControlServer()
        self._registry = RegistryClient(base_url=bridge_url)
```

Update `on_mount` to also kick off registration. Replace the existing `on_mount` body with:

```python
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
        self.run_worker(self._startup_register(), exclusive=False)

    async def _startup_register(self) -> None:
        ws_url = await self._control.start()
        payload = make_payload(
            session_id=self._session_id,
            cwd=self._cwd,
            ws_url=ws_url,
            model=self._model_id,
        )
        registered = await self._registry.register(payload)
        if registered:
            await self._registry.start_heartbeat(self._session_id)

    async def on_unmount(self) -> None:
        await self._registry.stop_heartbeat()
        await self._registry.deregister(self._session_id)
        await self._control.stop()
```

- [ ] **Step 6: Smoke-test manually**

```
# In one terminal:
.venv/bin/localllm

# In another:
curl -s http://127.0.0.1:9379/v1/cli/sessions | python -m json.tool
```

Expected: the running CLI session appears in the JSON list, with the correct `cwd`, `model`, and `ws_url`. Ctrl+C the CLI → next curl returns `[]`.

- [ ] **Step 7: Run the pre-push gate to close out M5**

```
bash .git/hooks/pre-push
```

Expected: exit 0.

- [ ] **Step 8: Commit**

```bash
git add localllm/control_server.py localllm/registry_client.py localllm/app.py tests/test_cli_registry_client.py
git commit -m "feat(cli): register session with bridge; heartbeat; bind no-op WS control server"
```

---

# Milestone 6 — Web mirror

End state: the existing web UI gets a "Live CLI Sessions" sidebar section and a Mirror View that live-streams a chosen CLI session's agent events.

## Task M6.1 — Fanout agent events into the registry

**Files:**

- Modify: `agent.py` (inside `react_loop_sse`, near each `await q.put(...)`)
- Create: `tests/test_cli_stream_fanout.py`

- [ ] **Step 1: Add a fanout helper at the top of `agent.py`**

Below the existing imports:

```python
from cli_sessions import get_registry as _get_cli_registry


async def _emit(task_id: str, cli_session_id: str | None, q: asyncio.Queue, event: dict) -> None:
    """Send an event to the per-task SSE queue and (optionally) fan out to CLI subscribers."""
    await q.put(json.dumps(event))
    if cli_session_id:
        await _get_cli_registry().fanout(cli_session_id, event)
```

- [ ] **Step 2: Replace every `await q.put(json.dumps({...}))` inside `react_loop_sse` with `await _emit(task_id, cli_session_id, q, {...})`**

Specifically inside `react_loop_sse` (agent.py:427), every event emission of the form:

```python
await q.put(json.dumps({"type": "...", ...}))
```

becomes:

```python
await _emit(task_id, cli_session_id, q, {"type": "...", ...})
```

Leave the sentinel `await q.put(None)` in the `finally:` block as-is — that's not an event, just a stream terminator. Also leave the inner deep-thinking-pipeline `q.put` calls alone; they don't need fanout for MVP.

- [ ] **Step 3: Write the integration test**

```python
# tests/test_cli_stream_fanout.py
import asyncio
import json

import pytest

import cli_sessions
from cli_sessions import SessionInfo


async def test_emit_fans_out_to_subscribers(monkeypatch):
    fresh = cli_sessions.SessionRegistry(snapshot_path=None or cli_sessions.DEFAULT_SNAPSHOT_PATH)  # noqa: SIM222
    monkeypatch.setattr(cli_sessions, "_registry", fresh)
    fresh.register(SessionInfo(
        session_id="cli-1", pid=1, cwd="/tmp", ws_url="ws://x", model="m",
        started_at="t", tty="", host="h",
    ))
    q = await fresh.subscribe("cli-1")

    # Late import so the monkeypatch is in effect
    from agent import _emit

    inproc_q: asyncio.Queue = asyncio.Queue()
    await _emit("task-1", "cli-1", inproc_q, {"type": "status", "message": "hi"})

    # CLI session subscriber receives the event
    delivered = await asyncio.wait_for(q.get(), timeout=1)
    assert delivered == {"type": "status", "message": "hi"}
    # And the per-task queue still got the original JSON string
    assert json.loads(await inproc_q.get())["message"] == "hi"


async def test_emit_without_cli_session_id_is_safe():
    from agent import _emit
    inproc_q: asyncio.Queue = asyncio.Queue()
    await _emit("task-1", None, inproc_q, {"type": "status", "message": "no-cli"})
    assert json.loads(await inproc_q.get())["message"] == "no-cli"
```

- [ ] **Step 4: Run the tests and verify they pass**

```
.venv/bin/python -m pytest tests/test_cli_stream_fanout.py tests/test_cli_sessions_registry.py -v
```

Expected: all PASS. (Existing agent tests should also still pass; run `tests/test_agent.py` to verify.)

- [ ] **Step 5: Commit**

```bash
git add agent.py tests/test_cli_stream_fanout.py
git commit -m "feat(bridge): fan out agent SSE events to CLI session subscribers"
```

## Task M6.2 — Pass-through routes in `gemma-web/server.js`

**Files:**

- Modify: `gemma-web/server.js`

- [ ] **Step 1: Inspect the existing SSE proxy helper**

```
grep -nE "(cli|agent.stream|event-stream|sse)" gemma-web/server.js | head -20
```

Identify the helper used for `/v1/agent/stream/:task_id` — call it `proxySSE(req, res, upstreamPath)`. The plan re-uses it.

- [ ] **Step 2: Add the two new routes**

In `gemma-web/server.js`, alongside the existing `/v1/agent/*` proxy block:

```javascript
// CLI session registry (read-only from the web side)
app.get("/v1/cli/sessions", async (req, res) => {
  try {
    const upstream = await fetch(`${BRIDGE_URL}/v1/cli/sessions`);
    const body = await upstream.text();
    res.status(upstream.status).type("application/json").send(body);
  } catch (err) {
    res.status(502).json({ error: String(err) });
  }
});

app.get("/v1/cli/stream/:sid", (req, res) => {
  proxySSE(req, res, `/v1/cli/stream/${req.params.sid}`);
});
```

(Replace `proxySSE` with the actual helper name in the file. If the existing file uses a different style — manual `http.request` piping — copy the existing `/v1/agent/stream/:task_id` block and edit the URL.)

- [ ] **Step 3: Restart the Node proxy and smoke-test**

```
# Restart Node proxy (existing pattern; check gemma-web/README or PROGRESS.md)
curl -s http://127.0.0.1:3001/v1/cli/sessions
```

Expected: same JSON as `http://127.0.0.1:9379/v1/cli/sessions`.

- [ ] **Step 4: Commit**

```bash
git add gemma-web/server.js
git commit -m "feat(web): proxy /v1/cli/sessions and /v1/cli/stream/:sid"
```

## Task M6.3 — Sidebar section + Mirror View in `index.html`

**Files:**

- Modify: `gemma-web/index.html`

This is HTML/JS edits — no unit tests; verify by browser inspection.

> **XSS posture:** `session_id`, `cwd`, and `model` come from the bridge's
> `/v1/cli/sessions`, which mirrors back whatever a local process POSTed to
> `/v1/cli/register`. The bridge is 127.0.0.1-only, but defense-in-depth
> matters — never interpolate those fields into `innerHTML`. Use
> `createElement` + `textContent` (the snippets below already do this).

- [ ] **Step 1: Add a sidebar section between "Scheduled Tasks" and "All Chats"**

Locate the existing scheduled-tasks section in `gemma-web/index.html` and add immediately after it:

```html
<details id="cli-sessions-section" class="sidebar-section">
  <summary>
    Live CLI Sessions <span id="cli-sessions-count" class="badge">0</span>
  </summary>
  <ul id="cli-sessions-list" class="sidebar-list"></ul>
</details>
```

Apply existing sidebar-section CSS (no new styles needed).

- [ ] **Step 2: Add the polling loop and mirror-view module in the `<script>` block**

Inside the main `<script>` block of `index.html`:

```javascript
// ---- Live CLI Sessions ----------------------------------------------------
let cliSessionsTimer = null;

function shortId(id) {
  return id ? id.slice(0, 8) : "—";
}

function basename(p) {
  if (!p) return "";
  const parts = p.split("/").filter(Boolean);
  return parts[parts.length - 1] || "/";
}

// Safe row builder: never set innerHTML with bridge-supplied values
// (session_id/cwd/model are user-controlled at the register endpoint).
function buildSessionRow(s) {
  const li = document.createElement("li");
  li.className = "sidebar-item";

  const dot = document.createElement("span");
  dot.className = "status-dot";
  dot.dataset.state = "idle";

  const title = document.createElement("span");
  title.className = "title";
  title.textContent = `${shortId(s.session_id)} · ${basename(s.cwd)}`;

  const meta = document.createElement("span");
  meta.className = "meta";
  meta.textContent = s.model || "";

  li.append(dot, title, meta);
  return li;
}

async function refreshCliSessions() {
  try {
    const r = await fetch("/v1/cli/sessions");
    if (!r.ok) return;
    const sessions = await r.json();
    const list = document.getElementById("cli-sessions-list");
    const count = document.getElementById("cli-sessions-count");
    count.textContent = String(sessions.length);
    // Clear children safely
    while (list.firstChild) list.removeChild(list.firstChild);
    for (const s of sessions) {
      const li = buildSessionRow(s);
      li.addEventListener("click", () => openCliMirror(s));
      list.appendChild(li);
    }
  } catch (err) {
    console.warn("cli-sessions refresh failed", err);
  }
}

function startCliSessionsPolling() {
  if (cliSessionsTimer) return;
  refreshCliSessions();
  cliSessionsTimer = setInterval(refreshCliSessions, 5000);
}

document.addEventListener("DOMContentLoaded", startCliSessionsPolling);

// ---- Mirror View ----------------------------------------------------------
let cliMirrorSSE = null;

function openCliMirror(session) {
  closeCliMirror(); // clean up any prior

  // Swap the main chat area into mirror mode
  const main = document.getElementById("chat-pane"); // existing main pane id
  main.dataset.mode = "cli-mirror";

  // Build banner + trace container with safe DOM APIs (session fields are
  // bridge-supplied and must not be interpolated into innerHTML).
  while (main.firstChild) main.removeChild(main.firstChild);

  const banner = document.createElement("div");
  banner.className = "mirror-banner";

  banner.appendChild(document.createTextNode("Mirroring "));
  const idCode = document.createElement("code");
  idCode.textContent = shortId(session.session_id);
  banner.appendChild(idCode);
  banner.appendChild(document.createTextNode(" — "));
  const cwdCode = document.createElement("code");
  cwdCode.textContent = session.cwd || "";
  banner.appendChild(cwdCode);
  banner.appendChild(
    document.createTextNode(" — input disabled (CLI owns input). ")
  );
  const detachBtn = document.createElement("button");
  detachBtn.id = "mirror-detach";
  detachBtn.textContent = "Detach";
  detachBtn.addEventListener("click", closeCliMirror);
  banner.appendChild(detachBtn);

  const trace = document.createElement("div");
  trace.id = "mirror-trace";
  trace.className = "agent-trace";

  main.append(banner, trace);

  const target = trace;
  cliMirrorSSE = new EventSource(`/v1/cli/stream/${session.session_id}`);
  cliMirrorSSE.onmessage = (e) => {
    try {
      const event = JSON.parse(e.data);
      // Reuse the existing agent-event renderer if available
      if (typeof renderAgentEvent === "function") {
        renderAgentEvent(target, event);
      } else {
        const div = document.createElement("div");
        div.textContent = JSON.stringify(event);
        target.appendChild(div);
      }
    } catch (err) {
      console.warn("mirror event parse error", err);
    }
  };
  cliMirrorSSE.onerror = (err) => {
    console.warn("mirror stream error", err);
  };
}

function closeCliMirror() {
  if (cliMirrorSSE) {
    cliMirrorSSE.close();
    cliMirrorSSE = null;
  }
  const main = document.getElementById("chat-pane");
  if (main && main.dataset.mode === "cli-mirror") {
    delete main.dataset.mode;
    // Caller should re-render the normal chat view here, using whatever
    // function the existing UI uses (e.g., renderActiveConversation()).
    if (typeof renderActiveConversation === "function") {
      renderActiveConversation();
    }
  }
}
```

> Note: the IDs `chat-pane`, the function names `renderAgentEvent` and `renderActiveConversation` are placeholders for whatever the existing file uses. **Inspect `index.html` first** (`grep -n "renderAgentEvent\|main-pane\|chat-pane" gemma-web/index.html`) and adjust the IDs/function names in the snippet to match the real ones before pasting. If those functions don't exist by exactly those names, copy the equivalent logic from the existing scheduled-tasks renderer pattern.

- [ ] **Step 3: Manual smoke test**

```
# Terminal 1: launch a CLI
.venv/bin/localllm
# (type something to start an agent task)

# Terminal 2 / browser: open the web UI
# Expand "Live CLI Sessions" → click the running CLI row → confirm
# the mirror pane streams the same trace
```

Expected: events appear in the browser within ~1s of appearing in the CLI; closing the CLI removes the row within 30 s.

- [ ] **Step 4: Run the pre-push gate to close out M6**

```
bash .git/hooks/pre-push
```

Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add gemma-web/index.html
git commit -m "feat(web): live CLI sessions sidebar + mirror view"
```

---

# Milestone 7 — Polish

End state: slash commands, reconnect, config file, README updated.

## Task M7.1 — Slash commands

**Files:**

- Create: `localllm/commands.py`
- Create: `tests/test_cli_commands.py`
- Modify: `localllm/app.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_commands.py
from localllm.commands import CommandResult, dispatch


def test_help_returns_help_text():
    result = dispatch("/help", model="gemma4-e4b")
    assert isinstance(result, CommandResult)
    assert result.kind == "show"
    assert "/help" in result.message


def test_model_sets_model():
    result = dispatch("/model gemma-31b", model="gemma4-e4b")
    assert result.kind == "set_model"
    assert result.value == "gemma-31b"


def test_clear():
    result = dispatch("/clear", model="x")
    assert result.kind == "clear"


def test_tools_lists_tools():
    result = dispatch("/tools", model="x")
    assert result.kind == "show"
    assert "read_file" in result.message


def test_cwd_returns_set_cwd():
    result = dispatch("/cwd /tmp", model="x")
    assert result.kind == "set_cwd"
    assert result.value == "/tmp"


def test_quit():
    result = dispatch("/quit", model="x")
    assert result.kind == "quit"


def test_unknown_command_returns_show_with_hint():
    result = dispatch("/wat", model="x")
    assert result.kind == "show"
    assert "unknown" in result.message.lower()


def test_non_command_returns_none():
    assert dispatch("hello world", model="x") is None
```

- [ ] **Step 2: Run and verify it fails**

```
.venv/bin/python -m pytest tests/test_cli_commands.py -v
```

Expected: FAIL (module missing).

- [ ] **Step 3: Implement `localllm/commands.py`**

```python
# localllm/commands.py
"""Slash-command dispatcher used by the TUI input box."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent_utils import TOOL_REGISTRY


HELP_TEXT = """Slash commands:
  /help              Show this help.
  /model <name>      Switch model (e.g., gemma4-e4b, gemma-31b).
  /clear             Clear the transcript.
  /tools             List available tools (safe vs risky).
  /cwd <path>        Change session cwd (sandbox root).
  /quit              Exit the CLI.
"""


@dataclass(frozen=True)
class CommandResult:
    kind: Literal["show", "set_model", "set_cwd", "clear", "quit"]
    message: str = ""
    value: str = ""


def _tools_text() -> str:
    lines = ["Available tools:"]
    for name in sorted(TOOL_REGISTRY):
        t = TOOL_REGISTRY[name]
        lines.append(f"  [{t.risk:5s}] {name:25s} {t.description}")
    return "\n".join(lines)


def dispatch(line: str, *, model: str) -> CommandResult | None:
    """Return a CommandResult for slash commands, None for plain prompts."""
    if not line.startswith("/"):
        return None
    parts = line.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        return CommandResult(kind="show", message=HELP_TEXT)
    if cmd == "/model":
        if not arg:
            return CommandResult(kind="show", message=f"current model: {model}")
        return CommandResult(kind="set_model", value=arg.strip())
    if cmd == "/clear":
        return CommandResult(kind="clear")
    if cmd == "/tools":
        return CommandResult(kind="show", message=_tools_text())
    if cmd == "/cwd":
        if not arg:
            return CommandResult(kind="show", message="usage: /cwd <path>")
        return CommandResult(kind="set_cwd", value=arg.strip())
    if cmd == "/quit":
        return CommandResult(kind="quit")
    return CommandResult(kind="show", message=f"unknown command: {cmd}\n\n{HELP_TEXT}")
```

- [ ] **Step 4: Run the test and verify it passes**

```
.venv/bin/python -m pytest tests/test_cli_commands.py -v
```

Expected: PASS.

- [ ] **Step 5: Wire dispatch into `app.py`'s `on_input_submitted`**

At the top of `on_input_submitted`, before the existing model call, add:

```python
        from localllm.commands import dispatch  # local: avoid early import for tests

        result = dispatch(text, model=self._model_id)
        if result is not None:
            if result.kind == "show":
                transcript.write_status(result.message)
                return
            if result.kind == "clear":
                transcript.clear()
                return
            if result.kind == "set_model":
                self._model_id = result.value
                status.model = result.value
                transcript.write_status(f"model → {result.value}")
                return
            if result.kind == "set_cwd":
                self._cwd = result.value
                status.cwd = result.value
                transcript.write_status(f"cwd → {result.value}")
                return
            if result.kind == "quit":
                self.exit()
                return
```

- [ ] **Step 6: Commit**

```bash
git add localllm/commands.py localllm/app.py tests/test_cli_commands.py
git commit -m "feat(cli): /help /model /clear /tools /cwd /quit slash commands"
```

## Task M7.2 — Config file + bridge reconnect

**Files:**

- Create: `localllm/config.py`
- Modify: `localllm/cli.py` (load config before launching app)
- Modify: `localllm/app.py` (reconnect message; exposes `/reconnect`)

- [ ] **Step 1: Implement `config.py`**

```python
# localllm/config.py
"""Reads ~/.localllm/config.toml. Falls back to sensible defaults."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".localllm"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULT_BRIDGE_URL = "http://127.0.0.1:9379"
DEFAULT_MODEL = "gemma4-e4b"


@dataclass
class Config:
    bridge_url: str = DEFAULT_BRIDGE_URL
    model: str = DEFAULT_MODEL


def ensure_dir() -> None:
    CONFIG_DIR.mkdir(mode=0o700, exist_ok=True, parents=True)


def load() -> Config:
    ensure_dir()
    if not CONFIG_FILE.exists():
        return Config()
    with CONFIG_FILE.open("rb") as f:
        data = tomllib.load(f)
    return Config(
        bridge_url=data.get("bridge_url", DEFAULT_BRIDGE_URL),
        model=data.get("model", DEFAULT_MODEL),
    )
```

- [ ] **Step 2: Use it in `cli.py`**

In `main()`, before the bridge-up probe:

```python
    from localllm.config import load as load_config

    cfg = load_config()
    # CLI args override file config; file overrides env via DEFAULT_BRIDGE_URL only
    if args.bridge_url == DEFAULT_BRIDGE_URL and cfg.bridge_url != DEFAULT_BRIDGE_URL:
        args.bridge_url = cfg.bridge_url
```

When launching the app:

```python
    app = LocalLLMApp(bridge_url=args.bridge_url, model_id=cfg.model)
```

(Add `model_id` to `LocalLLMApp.__init__` if not already there — it already is.)

- [ ] **Step 3: Add `/reconnect` slash command behavior in `app.py`**

In `on_input_submitted` exception handler (the `try/except` around the agent stream), already shows `bridge error: ...`. Make `/reconnect` re-issue a health probe and print the result:

In `commands.py`, add to `dispatch`:

```python
    if cmd == "/reconnect":
        return CommandResult(kind="show", message="reconnect: next prompt will retry the bridge.")
```

(The next prompt naturally retries — no extra wiring needed at the app level for MVP.)

- [ ] **Step 4: Commit**

```bash
git add localllm/config.py localllm/cli.py localllm/commands.py localllm/app.py
git commit -m "feat(cli): ~/.localllm/config.toml + /reconnect slash command"
```

## Task M7.3 — README update

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Append a CLI section**

Append at the bottom of `README.md`:

```markdown
## 🖥 CLI (`localllm`)

A Claude-Code-style terminal client. After installing the venv:

\`\`\`bash
pip install -e .
cd ~/Projects/your-project
localllm
\`\`\`

- Fully standalone — only the FastAPI bridge needs to be running.
- Tool calls are sandboxed to the directory you launched `localllm` from.
- Active CLI sessions appear in the web UI's "Live CLI Sessions" sidebar
  (read-only mirror; remote control comes in v2).

Slash commands: `/help`, `/model <name>`, `/clear`, `/tools`, `/cwd <path>`,
`/reconnect`, `/quit`.

Bridge URL defaults to `http://127.0.0.1:9379` and can be overridden via
`LOCALLLM_BRIDGE_URL`, `--bridge-url`, or `~/.localllm/config.toml`:

\`\`\`toml
bridge_url = "http://127.0.0.1:9379"
model = "gemma4-e4b"
\`\`\`
```

- [ ] **Step 2: Final pre-push gate to close the milestone**

```
bash .git/hooks/pre-push
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(cli): document the localllm CLI in README"
```

---

# Definition of Done

Per `CLAUDE.md`'s checklist (copy this into the final task report):

- [ ] All requested changes implemented across M1–M7.
- [ ] `bash .git/hooks/pre-push` ran and exited 0.
- [ ] Touched frontend (`gemma-web/index.html`, `gemma-web/server.js`) and sanity-checked by reading the files (and by browser if available).
- [ ] If pushed, GitHub Actions CI is green (or honestly reported red with diagnosis).

Plus the spec's manual checklist (spec §8.4):

- [ ] `localllm` launches in `~/Projects/LocalLLM`; status bar shows correct cwd + model.
- [ ] "read the README" → tool-call cards render; response streams.
- [ ] Ask agent to `shell("ls")` → confirm modal; Allow runs, Deny refuses.
- [ ] `curl http://127.0.0.1:9379/v1/cli/sessions` shows the session.
- [ ] Web sidebar shows the session; click → mirror streams same content.
- [ ] Ctrl-C in CLI → session disappears from web within 30 s.
