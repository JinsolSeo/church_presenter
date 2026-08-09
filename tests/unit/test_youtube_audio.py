from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal

from church_presenter.domain.enums import (
    AudioAvailability,
    AudioSourceType,
    PauseReason,
    PlaybackStatus,
)
from church_presenter.domain.models import AudioPlaylist, PlaylistItem
from church_presenter.media.audio_controller import AudioPlaybackController
from church_presenter.media.audio_router import AudioBackendRouter
from church_presenter.media.mock_backend import MockMediaBackend, MockStreamingAudioBackend
from church_presenter.media.playlist import YOUTUBE_URL_FILENAME, PlaylistService
from church_presenter.media.youtube_resolver import (
    YouTubeMetadata,
    YtDlpResolver,
    validate_youtube_url,
)


class FakeMetadataService(QObject):
    resolved = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.requests: dict[str, str] = {}
        self.cancelled: set[str] = set()
        self.closed = False

    def request_metadata(self, request_id: str, url: str) -> bool:
        if request_id in self.requests:
            return False
        self.requests[request_id] = url
        return True

    def cancel(self, request_id: str) -> None:
        self.cancelled.add(request_id)

    def close(self) -> None:
        self.closed = True


def audio_file(path: Path) -> Path:
    path.write_bytes(b"audio")
    return path


def test_validate_single_video_youtube_urls() -> None:
    assert validate_youtube_url("https://www.youtube.com/watch?v=abc123").endswith("abc123")
    assert validate_youtube_url("https://youtu.be/abc123") == "https://youtu.be/abc123"
    with pytest.raises(ValueError):
        validate_youtube_url("https://www.youtube.com/playlist?list=abc")
    with pytest.raises(ValueError):
        validate_youtube_url("https://example.com/watch?v=abc")


def test_resolver_preserves_stream_request_options(monkeypatch) -> None:
    resolver = YtDlpResolver()
    monkeypatch.setattr(
        resolver,
        "_extract",
        lambda _url: {
            "url": "https://stream.example/audio",
            "title": "Title",
            "webpage_url": "https://youtu.be/abc123",
            "http_headers": {
                "User-Agent": "Test Browser",
                "Referer": "https://www.youtube.com/",
                "Accept-Language": "ko-KR",
                "Injected": "bad\r\nHeader: value",
            },
            "downloader_options": {"http_chunk_size": 10_485_760},
            "protocol": "https",
            "acodec": "opus",
        },
    )

    result = resolver.stream("https://youtu.be/abc123")

    assert result.stream_url == "https://stream.example/audio"
    assert result.http_headers == (
        ("User-Agent", "Test Browser"),
        ("Referer", "https://www.youtube.com/"),
        ("Accept-Language", "ko-KR"),
    )
    assert result.http_chunk_size == 10_485_760
    assert result.protocol == "https"
    assert result.audio_codec == "opus"


def test_version_one_playlist_migrates_to_local_source(tmp_path: Path) -> None:
    track = audio_file(tmp_path / "legacy.wav")
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "items": [
                    {
                        "item_id": "legacy",
                        "path": track.name,
                        "relative": True,
                        "title": "Legacy",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    item = PlaylistService().load(path).items[0]
    assert item.source_type is AudioSourceType.LOCAL_FILE
    assert item.path == track
    assert item.availability is AudioAvailability.READY


def test_mixed_playlist_round_trip_preserves_youtube_fallback(tmp_path: Path) -> None:
    track = audio_file(tmp_path / "local.wav")
    fallback = audio_file(tmp_path / "fallback.wav")
    youtube = PlaylistItem.youtube(
        "youtube-id",
        "https://youtu.be/abc123",
        title="Service Stream",
        duration_ms=65_000,
        fallback_path=fallback,
        availability=AudioAvailability.UNAVAILABLE,
        metadata={"video_id": "abc123"},
        error_message="video unavailable",
    )
    playlist = AudioPlaylist(items=[PlaylistItem("local", track, "Local"), youtube])
    path = tmp_path / "mixed.json"
    service = PlaylistService()
    service.save(playlist, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert "stream_url" not in json.dumps(payload)
    loaded = service.load(path)
    restored = loaded.items[1]
    assert restored.source_type is AudioSourceType.YOUTUBE
    assert restored.source == "https://youtu.be/abc123"
    assert restored.fallback_path == fallback
    assert restored.metadata["video_id"] == "abc123"
    assert restored.availability is AudioAvailability.UNAVAILABLE
    assert restored.error_message == "video unavailable"


def test_folder_youtube_store_is_absent_by_default_and_uses_fixed_name(
    tmp_path: Path,
) -> None:
    service = PlaylistService()
    assert service.load_youtube_items(tmp_path) == []
    local = audio_file(tmp_path / "local.wav")
    fallback = audio_file(tmp_path / "fallback.wav")
    youtube = PlaylistItem.youtube(
        "youtube-id",
        "https://youtu.be/abc123",
        fallback_path=fallback,
    )

    saved = service.save_youtube_items(
        [PlaylistItem("local", local, "Local"), youtube],
        tmp_path,
    )

    assert saved == tmp_path / YOUTUBE_URL_FILENAME
    payload = json.loads(saved.read_text(encoding="utf-8"))
    assert payload == {
        "version": 1,
        "urls": [
            {
                "url": "https://youtu.be/abc123",
                "fallback_path": "fallback.wav",
                "fallback_relative": True,
            }
        ],
    }
    restored = service.load_youtube_items(tmp_path)
    assert len(restored) == 1
    assert restored[0].source == "https://youtu.be/abc123"
    assert restored[0].fallback_path == fallback
    assert restored[0].availability is AudioAvailability.UNRESOLVED


def test_folder_youtube_store_rejects_invalid_content(tmp_path: Path) -> None:
    (tmp_path / YOUTUBE_URL_FILENAME).write_text(
        json.dumps({"version": 1, "urls": ["https://example.com/not-youtube"]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="YouTube"):
        PlaylistService().load_youtube_items(tmp_path)


def test_invalid_playlist_source_type_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "items": [
                    {
                        "id": "bad",
                        "source_type": "radio",
                        "source": "https://example.com",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="source_type"):
        PlaylistService().load(path)


def test_router_selects_backend_and_stops_previous(tmp_path: Path) -> None:
    local_path = audio_file(tmp_path / "local.wav")
    local = MockMediaBackend()
    youtube = MockStreamingAudioBackend()
    router = AudioBackendRouter(local, youtube)
    router.prepare(PlaylistItem("local", local_path, "Local"))
    assert local.path == local_path
    assert router.path == local_path
    router.prepare(PlaylistItem.youtube("yt", "https://youtu.be/abc123"))
    assert local.status is PlaybackStatus.STOPPED
    assert youtube.source == "https://youtu.be/abc123"
    assert router.path is None


def test_youtube_failure_plays_local_fallback(tmp_path: Path) -> None:
    fallback = audio_file(tmp_path / "fallback.wav")
    local = MockMediaBackend()
    youtube = MockStreamingAudioBackend()
    url = "https://youtu.be/fails"
    youtube.fail_sources.add(url)
    router = AudioBackendRouter(local, youtube)
    metadata = FakeMetadataService()
    item = PlaylistItem.youtube("yt", url, fallback_path=fallback)
    controller = AudioPlaybackController(
        local,
        AudioPlaylist(items=[item], current_index=0),
        router=router,
        metadata_service=metadata,  # type: ignore[arg-type]
    )
    assert controller.play()
    assert controller.runtime.using_fallback
    assert controller.runtime.path == fallback
    assert controller.runtime.status is PlaybackStatus.PLAYING
    assert "fallback" in controller.runtime.status_message


def test_youtube_failure_without_fallback_becomes_error(tmp_path: Path) -> None:
    del tmp_path
    local = MockMediaBackend()
    youtube = MockStreamingAudioBackend()
    url = "https://youtu.be/fails"
    youtube.fail_sources.add(url)
    router = AudioBackendRouter(local, youtube)
    controller = AudioPlaybackController(
        local,
        AudioPlaylist(items=[PlaylistItem.youtube("yt", url)], current_index=0),
        router=router,
        metadata_service=FakeMetadataService(),  # type: ignore[arg-type]
    )
    assert controller.play()
    assert controller.runtime.status is PlaybackStatus.ERROR
    assert not controller.runtime.using_fallback


def test_metadata_result_updates_item_and_ignores_removed_item(tmp_path: Path) -> None:
    del tmp_path
    local = MockMediaBackend()
    metadata = FakeMetadataService()
    controller = AudioPlaybackController(
        local,
        router=AudioBackendRouter(local, MockStreamingAudioBackend()),
        metadata_service=metadata,  # type: ignore[arg-type]
    )
    item_id = controller.add_youtube_url("https://youtu.be/abc123")
    metadata.resolved.emit(
        item_id,
        YouTubeMetadata("Resolved title", 42_000, "abc123", "https://youtu.be/abc123"),
    )
    item = controller.playlist.items[0]
    assert item.title == "Resolved title"
    assert item.availability is AudioAvailability.READY
    controller.remove(0)
    metadata.resolved.emit(
        item_id,
        YouTubeMetadata("Late title", 1, "abc123", "https://youtu.be/abc123"),
    )
    assert controller.playlist.items == []


def test_stream_pause_for_video_and_cleanup() -> None:
    local = MockMediaBackend()
    youtube = MockStreamingAudioBackend()
    metadata = FakeMetadataService()
    controller = AudioPlaybackController(
        local,
        AudioPlaylist(
            items=[PlaylistItem.youtube("yt", "https://youtu.be/abc123")],
            current_index=0,
        ),
        router=AudioBackendRouter(local, youtube),
        metadata_service=metadata,  # type: ignore[arg-type]
    )
    assert controller.play()
    assert controller.pause_for_video()
    assert controller.runtime.status is PlaybackStatus.PAUSED
    assert controller.runtime.pause_reason is PauseReason.VIDEO
    controller.close()
    assert local.closed
    assert youtube.closed
    assert metadata.closed
