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


def test_snapshot_loaded_session_is_streamable(tmp_path):
    """After a bridge restart, load_snapshot repopulates _sessions but wipes
    _last_seen. The session is filtered out of list() until a heartbeat,
    but the stream endpoint's membership check must use _sessions (not list())
    so a mirror client can attach during the 10s gap. We don't open the
    full SSE stream (it's long-lived); we assert the underlying invariant:
    the session is present in _sessions and absent from list()."""
    snapshot = tmp_path / "sessions.json"
    snapshot.write_text(
        '{"cli-loaded": {"session_id": "cli-loaded", "pid": 1, '
        '"cwd": "/tmp", "ws_url": "ws://127.0.0.1:1/control", '
        '"model": "gemma4-e4b", "started_at": "2026-05-28T00:00:00Z", '
        '"tty": "", "host": "test"}}'
    )
    fresh = cli_sessions.SessionRegistry(snapshot_path=snapshot)
    fresh.load_snapshot()
    # list() filters by staleness — empty until heartbeat
    assert fresh.list() == []
    # _sessions (what stream_session now checks) contains the entry
    assert "cli-loaded" in fresh._sessions


def test_heartbeat_409_when_session_unknown(monkeypatch, tmp_path):
    """If the bridge has no record of the session (restart, eviction), the
    heartbeat endpoint returns 409 so the CLI knows to re-register."""
    fresh = cli_sessions.SessionRegistry(snapshot_path=tmp_path / "sessions.json")
    monkeypatch.setattr(cli_sessions, "_registry", fresh)

    client = TestClient(app)
    resp = client.post("/v1/cli/heartbeat", json={"session_id": "cli-never-registered"})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "unknown_session"
