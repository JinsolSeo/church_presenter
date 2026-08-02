from __future__ import annotations

import json
from pathlib import Path

import pytest

from church_presenter.domain.enums import ChannelRole, ContentType, PlaybackStatus
from church_presenter.domain.models import Content
from church_presenter.domain.state import ApplicationState
from church_presenter.media.mock_backend import MockMediaBackend
from church_presenter.media.video_manager import VideoPlaybackManager
from church_presenter.media.youtube_resolver import YtDlpResolver
from church_presenter.services.video_url_service import (
    VIDEO_URL_FILENAME,
    VideoUrlService,
)


def test_video_url_store_uses_fixed_name_and_round_trips(tmp_path: Path) -> None:
    service = VideoUrlService()
    first = "https://youtu.be/first123"
    second = "https://www.youtube.com/watch?v=second456"

    assert service.load(tmp_path) == []
    saved = service.save(tmp_path, [first, second, first])

    assert saved == tmp_path / VIDEO_URL_FILENAME
    assert service.load(tmp_path) == [first, second]
    payload = json.loads(saved.read_text(encoding="utf-8"))
    assert payload == {
        "version": 1,
        "urls": [{"url": first}, {"url": second}],
    }


def test_video_url_store_rejects_invalid_urls(tmp_path: Path) -> None:
    source = tmp_path / VIDEO_URL_FILENAME
    source.write_text(
        json.dumps({"version": 1, "urls": [{"url": "https://example.com/video"}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        VideoUrlService().load(tmp_path)

    source.write_text(
        json.dumps({"version": True, "urls": []}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        VideoUrlService().load(tmp_path)


def test_youtube_video_content_round_trip_and_take() -> None:
    url = "https://youtu.be/abc123"
    content = Content.youtube_video(url)

    restored = Content.from_dict(content.to_dict())
    assert restored.kind is ContentType.VIDEO
    assert restored.video_url == url
    assert restored.video_source == url

    state = ApplicationState()
    state.set_preview(ChannelRole.BROADCAST, restored)
    assert state.take(ChannelRole.BROADCAST) == (True, "")
    assert state.broadcast.live_content == restored


def test_video_manager_uses_same_cue_take_play_flow_for_url() -> None:
    backends: list[MockMediaBackend] = []

    def factory() -> MockMediaBackend:
        backend = MockMediaBackend(video=True)
        backends.append(backend)
        return backend

    manager = VideoPlaybackManager(factory)
    url = "https://youtu.be/abc123"
    results: list[tuple[ChannelRole, str, str]] = []
    manager.preview_result.connect(
        lambda role, source, _image, error: results.append((role, source, error))
    )

    manager.cue_preview(ChannelRole.BROADCAST, url)

    assert results[-1] == (ChannelRole.BROADCAST, url, "")
    assert manager.can_activate(ChannelRole.BROADCAST, url)
    assert manager.activate_preview(ChannelRole.BROADCAST, url)
    assert manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.LIVE_PAUSED
    assert manager.play(ChannelRole.BROADCAST)
    assert manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.PLAYING
    assert backends[0].path == url


def test_video_resolver_selects_a_combined_stream(monkeypatch) -> None:
    resolver = YtDlpResolver()
    captured: list[tuple[str, str]] = []

    def extract(url: str, selector: str) -> dict[str, object]:
        captured.append((url, selector))
        return {
            "id": "abc123",
            "title": "Video",
            "url": "https://stream.example/video.mp4",
            "vcodec": "avc1",
            "acodec": "mp4a",
            "protocol": "https",
        }

    monkeypatch.setattr(resolver, "_extract_with_format", extract)

    result = resolver.video_stream("https://youtu.be/abc123")

    assert result.stream_url == "https://stream.example/video.mp4"
    assert result.audio_codec == "mp4a"
    assert "vcodec!=none" in captured[0][1]
    assert "acodec!=none" in captured[0][1]
