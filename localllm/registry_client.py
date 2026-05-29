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
    def __init__(
        self, base_url: str = "http://127.0.0.1:9379", retries: int = 3
    ) -> None:
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
                    logger.warning(
                        "register failed: %s %s", resp.status_code, resp.text
                    )
            except httpx.HTTPError as exc:
                logger.warning("register attempt %d failed: %s", attempt + 1, exc)
            if attempt < self._retries - 1:
                await asyncio.sleep(1.0)
        return False

    async def heartbeat_once(self, session_id: str) -> bool:
        """3× retry w/ 1 s backoff per spec §7 (Heartbeat blip)."""
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.post(
                        f"{self._base}/v1/cli/heartbeat",
                        json={"session_id": session_id},
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
