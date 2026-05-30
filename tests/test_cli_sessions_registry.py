import asyncio
import json
import time
from pathlib import Path

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


def test_heartbeat_resets_staleness(tmp_path: Path):
    reg = SessionRegistry(snapshot_path=tmp_path / "sessions.json")
    reg.register(_info("cli-1"))
    reg._last_seen["cli-1"] = time.monotonic() - (HEARTBEAT_STALE_AFTER_S + 1)
    assert reg.list() == []
    reg.register(_info("cli-1"))  # re-register first
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
    assert (await asyncio.wait_for(q1.get(), 1)) == {
        "type": "status",
        "message": "hi",
    }
    assert (await asyncio.wait_for(q2.get(), 1)) == {
        "type": "status",
        "message": "hi",
    }


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


def test_init_does_not_create_snapshot_dir(tmp_path: Path):
    """Module import / SessionRegistry() must not touch the filesystem.
    The snapshot dir is created lazily on first write."""
    target = tmp_path / "deep" / "deeper" / "sessions.json"
    SessionRegistry(snapshot_path=target)
    assert not target.parent.exists()


def test_snapshot_is_atomic_replace(tmp_path: Path):
    """A write must leave no tmp files behind after success and must not
    truncate the existing file even if interrupted (we model this by
    checking that no .tmp files are left after a normal write)."""
    snapshot = tmp_path / "sessions.json"
    reg = SessionRegistry(snapshot_path=snapshot)
    reg.register(_info("cli-1"))
    reg.register(_info("cli-2"))
    assert snapshot.exists()
    leftover = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftover == []
    # File is valid JSON
    data = json.loads(snapshot.read_text())
    assert set(data.keys()) == {"cli-1", "cli-2"}


async def test_deregister_delivers_none_sentinel_when_queue_full(tmp_path: Path):
    """If a subscriber queue is full at deregister time, we must still
    deliver the None sentinel so the mirror SSE consumer sees end-of-stream."""
    reg = SessionRegistry(snapshot_path=tmp_path / "sessions.json", max_queue=2)
    reg.register(_info("cli-1"))
    q = await reg.subscribe("cli-1")
    await reg.fanout("cli-1", {"i": 1})
    await reg.fanout("cli-1", {"i": 2})
    # Queue is now full (size 2). Deregister must still drain a sentinel.
    reg.deregister("cli-1")
    # Drain to find the None — should be reachable after at most max_queue items
    saw_none = False
    for _ in range(3):
        try:
            item = q.get_nowait()
        except asyncio.QueueEmpty:
            break
        if item is None:
            saw_none = True
            break
    assert saw_none, "deregister must deliver None sentinel"


def test_evict_stale_removes_stale_entries(tmp_path: Path):
    reg = SessionRegistry(snapshot_path=tmp_path / "sessions.json")
    reg.register(_info("cli-fresh"))
    reg.register(_info("cli-stale"))
    reg._last_seen["cli-stale"] = time.monotonic() - (HEARTBEAT_STALE_AFTER_S + 1)
    evicted = reg.evict_stale()
    assert evicted == 1
    assert "cli-fresh" in reg._sessions
    assert "cli-stale" not in reg._sessions
