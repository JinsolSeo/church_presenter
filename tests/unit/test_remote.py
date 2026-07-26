from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

import aiohttp
import pytest

from church_presenter.remote.protocol import (
    KeyCommand,
    PointerCommand,
    WheelCommand,
    parse_input_message,
)
from church_presenter.remote.server import RemoteServerThread

ROOT = Path(__file__).resolve().parents[2]


def test_remote_protocol_validates_untrusted_input() -> None:
    pointer = parse_input_message(
        '{"type":"pointer","action":"press","x":0.5,"y":0.25,"button":"left"}'
    )
    wheel = parse_input_message(
        '{"type":"wheel","x":0.1,"y":0.9,"deltaX":10,"deltaY":-120}'
    )
    key = parse_input_message(
        '{"type":"key","action":"press","key":"PageDown","code":"PageDown","text":""}'
    )

    assert pointer == PointerCommand("press", 0.5, 0.25, "left")
    assert wheel == WheelCommand(0.1, 0.9, 10, -120)
    assert key == KeyCommand("press", "PageDown", "PageDown", "")
    assert parse_input_message(
        '{"type":"pointer","action":"press","x":1.1,"y":0.5,"button":"left"}'
    ) is None
    assert parse_input_message('{"type":"key","action":"press","key":""}') is None
    assert parse_input_message("not-json") is None
    assert parse_input_message('{"type":"shell","command":"whoami"}') is None


def _http_status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def test_server_authentication_port_fallback_frames_and_multiple_clients() -> None:
    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    first_port = occupied.getsockname()[1]
    started = threading.Event()
    counts_changed = threading.Event()
    selected_port = 0
    counts: list[int] = []
    commands: list[object] = []

    def on_started(port: int) -> None:
        nonlocal selected_port
        selected_port = port
        started.set()

    def on_clients(count: int) -> None:
        counts.append(count)
        if count >= 2:
            counts_changed.set()

    token = "correct-test-token"
    server = RemoteServerThread(
        token=token,
        host="127.0.0.1",
        first_port=first_port,
        last_port=first_port + 10,
        started=on_started,
        state_changed=lambda _state, _message: None,
        client_count_changed=on_clients,
        input_received=commands.append,
    )
    server.start()
    try:
        assert started.wait(3)
        assert selected_port > first_port
        base = f"http://127.0.0.1:{selected_port}"
        assert _http_status(f"{base}/connect") == 403
        assert _http_status(f"{base}/connect?token=wrong") == 403
        assert _http_status(f"{base}/connect?token={token}") == 200

        async def exercise_websockets() -> None:
            async with aiohttp.ClientSession() as session:
                try:
                    await session.ws_connect(f"{base}/ws?token=wrong")
                except aiohttp.WSServerHandshakeError as error:
                    assert error.status == 403
                else:
                    raise AssertionError("invalid WebSocket token was accepted")
                first = await session.ws_connect(f"{base}/ws?token={token}")
                second = await session.ws_connect(f"{base}/ws?token={token}")
                while not counts_changed.wait(0.01):
                    await asyncio.sleep(0.01)
                await first.send_str(
                    '{"type":"pointer","action":"press","x":0.5,"y":0.5,'
                    '"button":"left"}'
                )
                for _attempt in range(100):
                    if commands:
                        break
                    await asyncio.sleep(0.01)
                assert commands == [PointerCommand("press", 0.5, 0.5, "left")]
                server.publish_frame(
                    b"jpeg-data",
                    {
                        "type": "frame",
                        "width": 800,
                        "height": 450,
                        "window": "controller",
                        "sequence": 1,
                    },
                )
                metadata = await first.receive(timeout=2)
                frame = await first.receive(timeout=2)
                assert metadata.type is aiohttp.WSMsgType.TEXT
                assert '"sequence":1' in metadata.data
                assert frame.data == b"jpeg-data"
                await first.close()
                await second.close()

        asyncio.run(exercise_websockets())
        assert 1 in counts
        assert 2 in counts
    finally:
        server.request_stop()
        server.join(timeout=3)
        occupied.close()
    assert not server.is_alive()


def test_server_stop_requested_before_event_loop_is_not_lost() -> None:
    server = RemoteServerThread(
        token="immediate-stop-token",
        host="127.0.0.1",
        first_port=0,
        last_port=0,
        started=lambda _port: None,
        state_changed=lambda _state, _message: None,
        client_count_changed=lambda _count: None,
        input_received=lambda _command: None,
    )

    server.start()
    server.request_stop()
    server.join(timeout=3)

    assert not server.is_alive()


def test_remote_mobile_gesture_state_machine() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not available for the browser gesture test")
    result = subprocess.run(
        [
            node,
            ROOT / "tests/js/remote_gestures.test.mjs",
            ROOT / "src/church_presenter/remote/static/remote.js",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
