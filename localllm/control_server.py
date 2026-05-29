"""Tiny aiohttp WebSocket server bound to 127.0.0.1:0. MVP no-op handler."""

from __future__ import annotations

import logging
from contextlib import suppress

from aiohttp import WSMsgType, web

logger = logging.getLogger(__name__)


class ControlServer:
    """Hosts ws://127.0.0.1:<kernel-assigned>/control. Accept-and-discard for MVP;
    v2 will dispatch incoming control messages into the agent loop."""

    def __init__(self) -> None:
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._port: int = 0

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self._port}/control"

    async def start(self) -> str:
        app = web.Application()
        app.router.add_get("/control", self._handler)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await self._site.start()
        # Discover kernel-assigned port
        if self._runner.sites:
            site = next(iter(self._runner.sites))
            server = getattr(site, "_server", None)
            if server is not None and server.sockets:
                self._port = server.sockets[0].getsockname()[1]
        logger.info("control server up at %s", self.url)
        return self.url

    async def stop(self) -> None:
        if self._runner is not None:
            with suppress(Exception):
                await self._runner.cleanup()

    async def _handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                # MVP: accept-and-discard; v2 will dispatch into the agent.
                logger.debug("control msg ignored (v1): %s", msg.data[:200])
            elif msg.type == WSMsgType.ERROR:
                logger.warning("control ws error: %s", ws.exception())
        return ws
