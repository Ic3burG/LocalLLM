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

    def __init__(
        self, snapshot_path: Path | None = None, max_queue: int = 1000
    ) -> None:
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

    def heartbeat(self, session_id: str) -> bool:
        """Return True if the heartbeat refreshed a live session, False if
        the session is unknown (bridge restarted and lost it). Clients that
        get False should re-register."""
        if session_id not in self._sessions:
            return False
        self._last_seen[session_id] = time.monotonic()
        return True

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
        """Return only currently-live sessions; non-destructive so a heartbeat
        after a missed-deadline can reactivate the entry."""
        now = time.monotonic()
        return [
            info
            for sid, info in self._sessions.items()
            if now - self._last_seen.get(sid, 0) <= HEARTBEAT_STALE_AFTER_S
        ]

    def evict_stale(self) -> int:
        """Drop sessions past staleness threshold from in-memory state.
        Call periodically to keep _sessions from growing without bound."""
        now = time.monotonic()
        stale = [
            sid
            for sid in self._sessions
            if now - self._last_seen.get(sid, 0) > HEARTBEAT_STALE_AFTER_S
        ]
        for sid in stale:
            self._sessions.pop(sid, None)
            self._last_seen.pop(sid, None)
        return len(stale)

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
    """Accessor so agent.py can call get_registry().fanout(...) lazily."""
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
    refreshed = _registry.heartbeat(req.session_id)
    if not refreshed:
        # Bridge has no record of this session (restart, eviction). Tell the
        # CLI to re-register so the web sidebar can rediscover it.
        raise HTTPException(status_code=409, detail="unknown_session")
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
    # Check raw _sessions, not list() — list() filters stale by heartbeat
    # window, which means a freshly-restored session (load_snapshot wipes
    # _last_seen) would 404 in the 10s gap before its next heartbeat. The
    # mirror connection still works correctly because the publisher fans out
    # to subscribers regardless of staleness.
    if session_id not in _registry._sessions:
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
