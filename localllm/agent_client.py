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
    """Thin async wrapper over /v1/agent/{run,stream,confirm} + /v1/health."""

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
