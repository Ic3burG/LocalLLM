import time

from fastapi.testclient import TestClient

import cli_sessions
from gemma_bridge import app


def _payload(sid: str = "cli-test") -> dict:
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

    # Force cli-1 stale; list should drop it (non-destructively)
    fresh._last_seen["cli-1"] = time.monotonic() - 60
    listed = client.get("/v1/cli/sessions").json()
    assert {s["session_id"] for s in listed} == {"cli-2"}

    # Heartbeat brings cli-1 back without re-register because it's still in _sessions
    assert (
        client.post("/v1/cli/heartbeat", json={"session_id": "cli-1"}).status_code
        == 200
    )
    listed = client.get("/v1/cli/sessions").json()
    assert {s["session_id"] for s in listed} == {"cli-1", "cli-2"}

    # DELETE removes cli-1
    assert client.delete("/v1/cli/sessions/cli-1").status_code == 200
    listed = client.get("/v1/cli/sessions").json()
    assert {s["session_id"] for s in listed} == {"cli-2"}


def test_stream_404_for_unknown_session(monkeypatch, tmp_path):
    fresh = cli_sessions.SessionRegistry(snapshot_path=tmp_path / "sessions.json")
    monkeypatch.setattr(cli_sessions, "_registry", fresh)

    client = TestClient(app)
    with client.stream("GET", "/v1/cli/stream/cli-missing") as r:
        assert r.status_code == 404
