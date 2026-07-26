from __future__ import annotations

import importlib
import os
import sys

import pytest

from church_presenter.domain.enums import PlaybackStatus
from church_presenter.media.mpv_audio_backend import MpvAudioBackend
from church_presenter.media.youtube_resolver import YtDlpResolver


@pytest.mark.youtube_integration
def test_public_youtube_stream_resolves_without_download() -> None:
    url = os.environ.get("CHURCH_PRESENTER_YOUTUBE_TEST_URL", "")
    if not url:
        pytest.skip("set CHURCH_PRESENTER_YOUTUBE_TEST_URL for a public test video")
    pytest.importorskip("yt_dlp")
    result = YtDlpResolver().stream(url)
    assert result.stream_url.startswith(("http://", "https://"))
    assert result.metadata.original_url
    assert any(name.casefold() == "user-agent" for name, _value in result.http_headers)


@pytest.mark.mpv_integration
def test_python_mpv_can_load_system_runtime() -> None:
    if os.environ.get("CHURCH_PRESENTER_MPV_INTEGRATION") != "1":
        pytest.skip("set CHURCH_PRESENTER_MPV_INTEGRATION=1 for native mpv tests")
    try:
        module = importlib.import_module("mpv")
        options: dict[str, object] = {"video": False, "terminal": False}
        if sys.platform == "darwin":
            options.update(
                {
                    "macos_app_activation_policy": "prohibited",
                    "macos_menu_shortcuts": False,
                    "input_media_keys": False,
                }
            )
        player = module.MPV(**options)
    except (ImportError, OSError) as error:
        pytest.skip(f"libmpv runtime is unavailable: {error}")
    player.terminate()


@pytest.mark.youtube_integration
@pytest.mark.mpv_integration
def test_mpv_backend_streams_public_youtube_audio(qtbot) -> None:
    if os.environ.get("CHURCH_PRESENTER_MPV_INTEGRATION") != "1":
        pytest.skip("set CHURCH_PRESENTER_MPV_INTEGRATION=1 for native mpv tests")
    url = os.environ.get("CHURCH_PRESENTER_YOUTUBE_TEST_URL", "")
    if not url:
        pytest.skip("set CHURCH_PRESENTER_YOUTUBE_TEST_URL for a public test video")
    backend = MpvAudioBackend()
    loaded: list[bool] = []
    positions: list[int] = []
    errors: list[str] = []
    backend.loaded.connect(lambda: loaded.append(True))
    backend.position_changed.connect(positions.append)
    backend.error_occurred.connect(errors.append)
    backend.set_muted(True)
    try:
        backend.load(url)

        def prepared_or_failed() -> None:
            player = backend._player
            player_state = (
                {
                    name: getattr(player, name, None)
                    for name in (
                        "path",
                        "idle_active",
                        "core_idle",
                        "duration",
                        "pause",
                        "demuxer",
                    )
                }
                if player is not None
                else {}
            )
            assert loaded or errors, (
                f"status={backend.status.value}, player={backend._player is not None}, "
                f"stream_url={bool(backend._stream_url)}, "
                f"resolver_threads={backend.worker.pool.activeThreadCount()}, "
                f"init_threads={backend._init_pool.activeThreadCount()}, "
                f"player_state={player_state}"
            )

        qtbot.waitUntil(prepared_or_failed, timeout=30_000)
        assert errors == []
        assert backend.status is PlaybackStatus.READY
        backend.play()
        qtbot.waitUntil(
            lambda: any(position > 250 for position in positions) or bool(errors),
            timeout=20_000,
        )
        assert errors == []
        assert backend.status in {PlaybackStatus.PLAYING, PlaybackStatus.BUFFERING}
        backend.pause()
        assert backend.status is PlaybackStatus.PAUSED
        backend.seek(1000)
        backend.stop()
        assert backend.status is PlaybackStatus.STOPPED
    finally:
        backend.close()
