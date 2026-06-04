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
    """Thin async wrapper over /v1/agent/{run,stream,confirm} + /v1/health.

    Holds a single long-lived httpx.AsyncClient so keep-alive connections
    are reused across run/confirm/health calls. Callers can `await close()`
    explicitly or rely on GC; localhost socket leaks are bounded anyway."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:9379",
        request_timeout: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = httpx.Timeout(request_timeout, read=None)
        # One AsyncClient per AgentClient — httpx pools connections to the
        # same host, so per-call POST/GET reuses the keep-alive socket.
        self._client = httpx.AsyncClient(timeout=self._timeout)
        # Separate short-timeout client for health probes so they can't
        # block on the read=None of the streaming client. 5s (not 2s) so a
        # bridge that has bound the port but is still finishing its heavy
        # cold-start imports isn't falsely reported unreachable.
        self._health_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))

    async def close(self) -> None:
        await self._client.aclose()
        await self._health_client.aclose()

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

        resp = await self._client.post(f"{self._base}/v1/agent/run", json=payload)
        resp.raise_for_status()
        task_id = resp.json()["task_id"]
        async with aconnect_sse(
            self._client, "GET", f"{self._base}/v1/agent/stream/{task_id}"
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
        resp = await self._client.post(
            f"{self._base}/v1/agent/confirm/{task_id}",
            json={"approved": approved},
        )
        resp.raise_for_status()

    async def health(self) -> bool:
        """Probe /v1/health. Returns True iff status code is 200."""
        try:
            resp = await self._health_client.get(f"{self._base}/v1/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def list_models(self) -> list[str]:
        """Available model ids from /v1/models, de-duplicated, order preserved.

        Returns an empty list if the bridge is unreachable or errors — callers
        treat that as 'no models to pick from' rather than crashing the TUI."""
        try:
            resp = await self._health_client.get(f"{self._base}/v1/models")
            if resp.status_code != 200:
                return []
            data = resp.json().get("data", [])
        except httpx.HTTPError:
            return []
        seen: set[str] = set()
        out: list[str] = []
        for item in data:
            mid = item.get("id")
            if mid and mid not in seen:
                seen.add(mid)
                out.append(mid)
        return out

    async def health_detail(self, model_id: str = "gemma4-e4b") -> dict | None:
        """Full /v1/health response. Returns None if the bridge is unreachable."""
        try:
            resp = await self._health_client.get(
                f"{self._base}/v1/health", params={"model_id": model_id}
            )
            if resp.status_code != 200:
                return None
            return resp.json()
        except httpx.HTTPError:
            return None
