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
        {
            "type": "step",
            "tool": "read_file",
            "args": {"0": "README.md"},
            "result": "hi",
            "elapsed_ms": 5,
        },
        {"type": "done", "message": "summary"},
    ]
    app = make_stub_app(events)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
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


async def test_health_returns_false_when_route_missing(stub_server):
    base_url, _ = stub_server
    # The stub doesn't define /v1/health, so health() returns False.
    client = AgentClient(base_url=base_url)
    assert await client.health() is False
