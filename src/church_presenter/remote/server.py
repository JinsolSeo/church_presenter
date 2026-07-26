from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from aiohttp import WSMsgType, web

from church_presenter.remote.protocol import RemoteCommand, parse_input_message

DEFAULT_PORT = 8765
LAST_PORT = 8790
SESSION_COOKIE = "church_presenter_remote"
STATIC_DIR = Path(__file__).with_name("static")


@dataclass(slots=True)
class _Client:
    websocket: web.WebSocketResponse
    frames: asyncio.Queue[tuple[bytes, dict[str, object]]]


class _InputRateLimiter:
    def __init__(self, rate: float = 180.0, burst: float = 240.0) -> None:
        self.rate = rate
        self.capacity = burst
        self.tokens = burst
        self.updated = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


class RemoteServerThread(threading.Thread):
    """Own one aiohttp server and its asyncio loop."""

    def __init__(
        self,
        *,
        token: str,
        host: str = "0.0.0.0",
        first_port: int = DEFAULT_PORT,
        last_port: int = LAST_PORT,
        started: Callable[[int], None],
        state_changed: Callable[[str, str], None],
        client_count_changed: Callable[[int], None],
        input_received: Callable[[RemoteCommand], None],
    ) -> None:
        super().__init__(name="church-presenter-remote", daemon=True)
        self.host = host
        self.first_port = first_port
        self.last_port = last_port
        self._token = token
        self._started_callback = started
        self._state_callback = state_changed
        self._client_count_callback = client_count_changed
        self._input_callback = input_received
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._stop_requested = threading.Event()
        self._clients: dict[str, _Client] = {}
        self._sessions: set[str] = set()

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        except Exception as error:
            self._state_callback("error", str(error))
        finally:
            self._sessions.clear()
            self._clients.clear()
            self._loop = None
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    async def _serve(self) -> None:
        self._stop_event = asyncio.Event()
        if self._stop_requested.is_set():
            self._stop_event.set()
        app = web.Application(client_max_size=8192)
        app.router.add_get("/", self._redirect_root)
        app.router.add_get("/connect", self._connect)
        app.router.add_get("/remote.js", self._javascript)
        app.router.add_get("/remote.css", self._stylesheet)
        app.router.add_get("/ws", self._websocket)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        selected_port: int | None = None
        try:
            for port in range(self.first_port, self.last_port + 1):
                site = web.TCPSite(runner, self.host, port)
                try:
                    await site.start()
                except OSError:
                    continue
                selected_port = port
                break
            if selected_port is None:
                self._state_callback("error", "포트 8765-8790을 사용할 수 없습니다.")
                return
            self._started_callback(selected_port)
            self._state_callback("waiting", "")
            await self._stop_event.wait()
        finally:
            clients = list(self._clients.values())
            for client in clients:
                with contextlib.suppress(Exception):
                    await client.websocket.close(
                        code=1001,
                        message=b"Remote server stopped",
                    )
            await runner.cleanup()
            self._client_count_callback(0)
            self._state_callback("stopped", "")

    def request_stop(self) -> None:
        self._token = ""
        self._stop_requested.set()
        loop = self._loop
        event = self._stop_event
        if loop is not None and event is not None:
            loop.call_soon_threadsafe(event.set)

    def publish_frame(self, jpeg: bytes, metadata: dict[str, object]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._publish_on_loop, jpeg, metadata)

    def _publish_on_loop(self, jpeg: bytes, metadata: dict[str, object]) -> None:
        for client in self._clients.values():
            queue = client.frames
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait((jpeg, metadata))

    def _is_authorized(self, request: web.Request) -> bool:
        supplied = request.query.get("token", "")
        if self._token and supplied and secrets.compare_digest(supplied, self._token):
            return True
        session = request.cookies.get(SESSION_COOKIE, "")
        return bool(session and session in self._sessions)

    async def _redirect_root(self, _request: web.Request) -> web.Response:
        raise web.HTTPForbidden(text="인증 토큰이 필요합니다.")

    async def _connect(self, request: web.Request) -> web.StreamResponse:
        if not self._is_authorized(request):
            raise web.HTTPForbidden(text="유효하지 않은 원격 연결입니다.")
        response = web.FileResponse(STATIC_DIR / "index.html")
        if request.query.get("token"):
            session = secrets.token_urlsafe(32)
            self._sessions.add(session)
            response.set_cookie(
                SESSION_COOKIE,
                session,
                httponly=True,
                samesite="Strict",
                max_age=8 * 60 * 60,
            )
        return response

    async def _javascript(self, request: web.Request) -> web.StreamResponse:
        if not self._is_authorized(request):
            raise web.HTTPForbidden()
        return web.FileResponse(STATIC_DIR / "remote.js")

    async def _stylesheet(self, request: web.Request) -> web.StreamResponse:
        if not self._is_authorized(request):
            raise web.HTTPForbidden()
        return web.FileResponse(STATIC_DIR / "remote.css")

    async def _websocket(self, request: web.Request) -> web.StreamResponse:
        if not self._is_authorized(request):
            raise web.HTTPForbidden(text="유효하지 않은 원격 연결입니다.")
        websocket = web.WebSocketResponse(heartbeat=20.0, max_msg_size=8192)
        await websocket.prepare(request)
        identifier = secrets.token_hex(12)
        client = _Client(websocket, asyncio.Queue(maxsize=1))
        self._clients[identifier] = client
        self._client_count_callback(len(self._clients))
        limiter = _InputRateLimiter()
        sender = asyncio.create_task(self._send_frames(client))
        try:
            async for message in websocket:
                if message.type is WSMsgType.TEXT and limiter.allow():
                    command = parse_input_message(message.data)
                    if command is not None:
                        self._input_callback(command)
                elif message.type is WSMsgType.ERROR:
                    break
        finally:
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender
            self._clients.pop(identifier, None)
            self._client_count_callback(len(self._clients))
        return websocket

    @staticmethod
    async def _send_frames(client: _Client) -> None:
        while True:
            jpeg, metadata = await client.frames.get()
            await client.websocket.send_str(json.dumps(metadata, separators=(",", ":")))
            await client.websocket.send_bytes(jpeg)
