"""LiveKit transport adapter — room lifecycle, token generation, HTTP server.

Responsibilities:
  - Create LiveKit room (UUID name) for each session.
  - Mint short-lived participant JWT via ``livekit-api``.
  - Serve ``GET /token``, ``GET /health``, and static ``client/`` files via aiohttp.
  - Send state/metric/transcript events to the browser via LiveKit data channel.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import structlog
from aiohttp import web

log = structlog.get_logger(__name__)


def _mint_token(
    api_key: str,
    api_secret: str,
    room_name: str,
    identity: str,
) -> str:
    """Generate a LiveKit participant JWT."""
    from livekit.api import AccessToken, VideoGrants

    token = (
        AccessToken(api_key=api_key, api_secret=api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(VideoGrants(room_join=True, room=room_name))
        .with_ttl(datetime.timedelta(hours=1))  # 1 hour
        .to_jwt()
    )
    return token


class LiveKitServer:
    """aiohttp HTTP server that serves token endpoint + static client files."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        livekit_url: str,
        host: str = "localhost",
        port: int = 7860,
        static_dir: str = "client",
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._livekit_url = livekit_url
        self._host = host
        self._port = port
        self._static_dir = Path(static_dir)

        self._room_name: str = f"voice-agent-{uuid.uuid4().hex[:8]}"
        self._session_state: str = "INITIALIZING"
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._start_time = time.monotonic()

    @property
    def room_name(self) -> str:
        return self._room_name

    def update_state(self, state: str) -> None:
        self._session_state = state

    # ─────────────────────────────────────────────── HTTP setup / teardown ──

    async def start(self) -> None:
        self._app = web.Application()
        self._app.router.add_get("/token", self._handle_token)
        self._app.router.add_get("/health", self._handle_health)
        self._app.router.add_get("/", self._handle_index)
        if self._static_dir.exists():
            self._app.router.add_static("/", str(self._static_dir), name="static")

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        log.info(
            "http_server_started",
            url=f"http://{self._host}:{self._port}",
            room=self._room_name,
        )

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    # ─────────────────────────────────────────────────────── handlers ────

    async def _handle_token(self, request: web.Request) -> web.Response:
        identity = request.rel_url.query.get("identity", f"user-{uuid.uuid4().hex[:6]}")
        try:
            token = _mint_token(
                self._api_key,
                self._api_secret,
                self._room_name,
                identity,
            )
            return web.json_response(
                {
                    "token": token,
                    "url": self._livekit_url,
                    "room": self._room_name,
                }
            )
        except Exception as exc:
            log.error("token_generation_error", error=str(exc))
            return web.json_response({"error": str(exc)}, status=500)

    async def _handle_index(self, _request: web.Request) -> web.FileResponse:
        index = self._static_dir / "index.html"
        return web.FileResponse(index)

    async def _handle_health(self, _request: web.Request) -> web.Response:
        uptime = round(time.monotonic() - self._start_time, 1)
        healthy = self._session_state not in ("DEGRADED", "SHUTDOWN")
        return web.json_response(
            {
                "status": "ok" if healthy else "degraded",
                "state": self._session_state,
                "uptime_s": uptime,
            },
            status=200 if healthy else 503,
        )
