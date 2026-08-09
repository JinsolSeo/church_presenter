from __future__ import annotations

import os

import pytest

from church_presenter.domain.enums import PlaybackStatus
from church_presenter.media.qt_media_backend import QtMediaBackend
from church_presenter.media.youtube_resolver import YtDlpResolver


@pytest.mark.youtube_integration
def test_public_youtube_stream_resolves_without_download() -> None:
    url = os.environ.get("CHURCH_PRESENTER_YOUTUBE_TEST_URL", "")
    if not url:
        pytest.skip("set CHURCH_PRESENTER_YOUTUBE_TEST_URL for a public test video")
    pytest.importorskip("yt_dlp")
    result = YtDlpResolver().video_stream(url)
    assert result.stream_url.startswith(("http://", "https://"))
    assert result.metadata.original_url
    assert any(name.casefold() == "user-agent" for name, _value in result.http_headers)


@pytest.mark.youtube_integration
@pytest.mark.media_integration
def test_qt_backend_streams_public_youtube_audio(qtbot) -> None:
    if os.environ.get("CHURCH_PRESENTER_MEDIA_INTEGRATION") != "1":
        pytest.skip("set CHURCH_PRESENTER_MEDIA_INTEGRATION=1 for Qt media tests")
    url = os.environ.get("CHURCH_PRESENTER_YOUTUBE_TEST_URL", "")
    if not url:
        pytest.skip("set CHURCH_PRESENTER_YOUTUBE_TEST_URL for a public test video")
    backend = QtMediaBackend(video=False, streaming=True)
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
            assert loaded or errors, (
                f"status={backend.status.value}, diagnostic={backend.diagnostic()}"
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
        assert backend.status is PlaybackStatus.PLAYING
        backend.pause()
        assert backend.status is PlaybackStatus.PAUSED
        backend.seek(1000)
        backend.stop()
        assert backend.status is PlaybackStatus.STOPPED
    finally:
        backend.close()
