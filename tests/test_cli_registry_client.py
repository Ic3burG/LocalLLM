import asyncio

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
    spawned: list = []

    async def _start(status_code: int = 200):
        app = make_stub(status_code)
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        spawned.append((server, task))
        return f"http://127.0.0.1:{port}", app.state.shared

    yield _start

    for server, task in spawned:
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
    sleeps: list = []

    async def fake_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr("localllm.registry_client.asyncio.sleep", fake_sleep)
    client = RegistryClient(base_url="http://127.0.0.1:1")  # nothing listening
    ok = await client.heartbeat_once("cli-1")
    assert ok is False
    assert sleeps == [1.0, 1.0]  # 3 attempts, 2 sleeps between them


def make_409_then_ok_stub():
    """Bridge that 409s on heartbeat the first time (unknown session),
    accepts a fresh register, then 200s on subsequent heartbeats. Models
    the 'bridge restarted and lost in-memory state' scenario."""
    from fastapi import FastAPI, HTTPException

    app = FastAPI()
    state: dict = {"known": False, "calls": []}

    @app.post("/v1/cli/register")
    async def reg(payload: dict):
        state["known"] = True
        state["calls"].append(("register", payload))
        return {"ok": True}

    @app.post("/v1/cli/heartbeat")
    async def hb(payload: dict):
        state["calls"].append(("heartbeat", payload))
        if not state["known"]:
            raise HTTPException(status_code=409, detail="unknown_session")
        return {"ok": True}

    app.state.shared = state
    return app


async def test_heartbeat_409_triggers_reregister(stub_server):
    # Spin a custom stub that emulates the post-restart scenario.
    import uvicorn

    app = make_409_then_ok_stub()
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        client = RegistryClient(base_url=f"http://127.0.0.1:{port}")
        # Pre-register so the cache is populated
        payload = make_payload(
            "cli-1", "/tmp", "ws://127.0.0.1:1/control", "gemma4-e4b"
        )
        await client.register(payload)
        # Simulate bridge restart: server forgot the session
        app.state.shared["known"] = False
        # Heartbeat sees 409, falls back to register
        ok = await client.heartbeat_once("cli-1")
        assert ok is True
        kinds = [c[0] for c in app.state.shared["calls"]]
        # register (initial) + heartbeat (409) + register (fallback)
        assert kinds.count("register") == 2
        assert kinds.count("heartbeat") == 1
    finally:
        server.should_exit = True
        await task
