"""Tests for the SSE fanout: agent events should reach CLI session subscribers."""

import asyncio
import json

import cli_sessions
from agent import _FanoutQueue
from cli_sessions import SessionInfo


def _info(sid: str = "cli-1") -> SessionInfo:
    return SessionInfo(
        session_id=sid,
        pid=1,
        cwd="/tmp",
        ws_url="ws://127.0.0.1:1/control",
        model="gemma4-e4b",
        started_at="2026-05-28T00:00:00Z",
        tty="",
        host="test",
    )


async def test_fanout_queue_mirrors_events_to_registry(monkeypatch, tmp_path):
    fresh = cli_sessions.SessionRegistry(snapshot_path=tmp_path / "sessions.json")
    monkeypatch.setattr(cli_sessions, "_registry", fresh)
    fresh.register(_info("cli-1"))
    subscriber = await fresh.subscribe("cli-1")

    inner: asyncio.Queue = asyncio.Queue()
    wrapped = _FanoutQueue(inner, cli_session_id="cli-1")

    payload = json.dumps({"type": "status", "message": "hi"})
    await wrapped.put(payload)

    # The inner queue still receives the original JSON string …
    assert (await inner.get()) == payload
    # … and the registry subscriber receives the parsed dict.
    delivered = await asyncio.wait_for(subscriber.get(), timeout=1)
    assert delivered == {"type": "status", "message": "hi"}


async def test_fanout_queue_without_session_id_is_transparent():
    inner: asyncio.Queue = asyncio.Queue()
    wrapped = _FanoutQueue(inner, cli_session_id=None)
    await wrapped.put(json.dumps({"type": "done", "message": "ok"}))
    item = await inner.get()
    assert json.loads(item)["message"] == "ok"


async def test_fanout_queue_passes_through_non_string_items():
    """The sentinel `await q.put(None)` and other non-event payloads should
    not crash the wrapper."""
    inner: asyncio.Queue = asyncio.Queue()
    wrapped = _FanoutQueue(inner, cli_session_id="cli-1")
    await wrapped.put(None)
    assert (await inner.get()) is None


async def test_fanout_queue_handles_malformed_json(monkeypatch, tmp_path):
    fresh = cli_sessions.SessionRegistry(snapshot_path=tmp_path / "sessions.json")
    monkeypatch.setattr(cli_sessions, "_registry", fresh)
    fresh.register(_info("cli-1"))

    inner: asyncio.Queue = asyncio.Queue()
    wrapped = _FanoutQueue(inner, cli_session_id="cli-1")
    await wrapped.put("not json")  # must not raise
    assert (await inner.get()) == "not json"
