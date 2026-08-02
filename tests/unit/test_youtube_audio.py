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
from church_presenter.media import mpv_audio_backend
from church_presenter.media.audio_controller import AudioPlaybackController
from church_presenter.media.audio_router import AudioBackendRouter
from church_presenter.media.mock_backend import MockMediaBackend, MockStreamingAudioBackend
from church_presenter.media.mpv_audio_backend import MpvAudioBackend
from church_presenter.media.playlist import YOUTUBE_URL_FILENAME, PlaylistService
from church_presenter.media.youtube_resolver import (
    ResolvedYouTubeStream,
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


class FakeStreamWorker(QObject):
    resolved = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.request_id = ""
        self.cancelled = ""
        self.closed = False

    def request_stream(self, request_id: str, _url: str) -> bool:
        self.request_id = request_id
        return True

    def cancel(self, request_id: str) -> None:
        self.cancelled = request_id

    def close(self) -> None:
        self.closed = True


class FakeMpvEvent:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def as_dict(self) -> dict[str, object]:
        return self.payload


class FakeMpvPlayer:
    def __init__(self) -> None:
        self.pause = True
        self.volume = 100.0
        self.user_agent = ""
        self.referrer = ""
        self.http_header_fields: list[str] = []
        self.curl_max_request_size = 0
        self.mpv_version_tuple = (0, 41, 0)
        self.audio_device = "auto"
        self.audio_device_list: list[dict[str, str]] = []
        self.loaded_url = ""
        self.path = ""
        self.duration: float | None = None
        self.time_pos: float | None = None
        self.eof_reached = False
        self.cache_buffering_state: float | None = None
        self.core_idle = False
        self.idle_active = True
        self.observers: dict[str, object] = {}
        self.event_callback: object | None = None
        self.terminated = False

    def observe_property(self, name: str, callback: object) -> None:
        self.observers[name] = callback

    def register_event_callback(self, callback: object) -> None:
        self.event_callback = callback

    def loadfile(self, url: str, _mode: str) -> None:
        self.loaded_url = url
        self.path = url

    def terminate(self) -> None:
        self.terminated = True


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


def test_windows_libmpv_search_registers_configured_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dll_directory = tmp_path / "portable-mpv"
    dll_directory.mkdir()
    (dll_directory / "mpv-2.dll").write_bytes(b"test")
    registered: list[str] = []
    monkeypatch.setattr(mpv_audio_backend.sys, "platform", "win32")
    monkeypatch.setenv("CHURCH_PRESENTER_LIBMPV_DIR", str(dll_directory))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(
        mpv_audio_backend.os,
        "add_dll_directory",
        lambda value: registered.append(value) or object(),
        raising=False,
    )
    monkeypatch.setattr(
        mpv_audio_backend,
        "_WINDOWS_DLL_DIRECTORY_HANDLES",
        [],
    )

    found = mpv_audio_backend._configure_windows_libmpv_search()

    assert found == (dll_directory.resolve(),)
    assert registered == [str(dll_directory.resolve())]
    assert str(dll_directory.resolve()) in mpv_audio_backend.os.environ["PATH"]


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


def test_mpv_backend_normalizes_loaded_transport_and_callbacks(qtbot) -> None:
    del qtbot
    worker = FakeStreamWorker()
    backend = MpvAudioBackend(worker=worker)  # type: ignore[arg-type]
    loaded: list[bool] = []
    backend.loaded.connect(lambda: loaded.append(True))
    backend.load("https://youtu.be/abc123")
    request_id = worker.request_id
    stream = ResolvedYouTubeStream(
        "https://stream.example/audio",
        YouTubeMetadata("Title", 10_000, "abc123", "https://youtu.be/abc123"),
        http_headers=(
            ("User-Agent", "Test Browser"),
            ("Referer", "https://www.youtube.com/"),
            ("Accept-Language", "ko-KR"),
        ),
        http_chunk_size=10_485_760,
        protocol="https",
        audio_codec="opus",
    )
    backend._stream_url = stream.stream_url
    backend._stream_headers = stream.http_headers
    backend._stream_http_chunk_size = stream.http_chunk_size
    player = FakeMpvPlayer()
    backend._mpv_initialized(request_id, player)
    assert player.loaded_url == stream.stream_url
    assert player.user_agent == "Test Browser"
    assert player.referrer == "https://www.youtube.com/"
    assert player.http_header_fields == ["Accept-Language: ko-KR"]
    assert player.curl_max_request_size == 10_485_760
    assert callable(player.event_callback)
    player.event_callback(FakeMpvEvent({"event_id": 8}))  # type: ignore[operator]
    assert loaded == [True]
    assert backend.status is PlaybackStatus.READY
    backend.play()
    assert backend.status is PlaybackStatus.PLAYING
    backend.pause()
    assert backend.status is PlaybackStatus.PAUSED
    backend.close()
    assert player.terminated
    assert worker.closed


def test_mpv_backend_maps_qt_output_to_libmpv_device(qtbot) -> None:
    del qtbot

    class FakeByteArray:
        def data(self) -> bytes:
            return b"{01234567-89AB-CDEF-0123-456789ABCDEF}"

    class FakeAudioDevice:
        def isNull(self) -> bool:
            return False

        def description(self) -> str:
            return "USB Audio Device"

        def id(self) -> FakeByteArray:
            return FakeByteArray()

    worker = FakeStreamWorker()
    backend = MpvAudioBackend(
        worker=worker,  # type: ignore[arg-type]
        audio_device_resolver=lambda _device_id: FakeAudioDevice(),
    )
    assert backend.set_audio_output_device("persisted-device-id")
    player = FakeMpvPlayer()
    player.audio_device_list = [
        {"name": "auto", "description": "Autoselect device"},
        {
            "name": "wasapi/{01234567-89ab-cdef-0123-456789abcdef}",
            "description": "Speakers (USB Audio Device)",
        },
    ]

    assert backend._apply_audio_output_device(player)
    assert player.audio_device == "wasapi/{01234567-89ab-cdef-0123-456789abcdef}"
    backend.close()


def test_mpv_backend_prepare_timeout_reports_error(qtbot) -> None:
    del qtbot
    worker = FakeStreamWorker()
    backend = MpvAudioBackend(worker=worker)  # type: ignore[arg-type]
    errors: list[str] = []
    backend.error_occurred.connect(errors.append)
    backend.load("https://youtu.be/abc123")
    request_id = worker.request_id

    backend._prepare_timeout()

    assert backend.status is PlaybackStatus.ERROR
    assert errors and "30초" in errors[-1]
    assert worker.cancelled == request_id
    assert backend._request_id == ""
    backend.close()


def test_mpv_backend_polling_fallback_emits_ready_progress_and_end(qtbot) -> None:
    del qtbot
    worker = FakeStreamWorker()
    backend = MpvAudioBackend(worker=worker)  # type: ignore[arg-type]
    loaded: list[bool] = []
    durations: list[int] = []
    positions: list[int] = []
    ended: list[bool] = []
    backend.loaded.connect(lambda: loaded.append(True))
    backend.duration_changed.connect(durations.append)
    backend.position_changed.connect(positions.append)
    backend.ended.connect(lambda: ended.append(True))
    backend.load("https://youtu.be/abc123")
    positions.clear()
    request_id = worker.request_id
    backend._stream_url = "https://stream.example/audio"
    player = FakeMpvPlayer()
    backend._mpv_initialized(request_id, player)
    player.duration = 10.0
    player.time_pos = 0.5
    player.core_idle = True
    player.idle_active = False
    backend._poll_player()
    backend._duration(request_id, "duration", 10.0)
    backend._time_position(request_id, "time-pos", 0.5)
    assert loaded == [True]
    assert durations == [10_000]
    assert positions == [500]
    player.eof_reached = True
    backend._poll_player()
    backend._eof_reached(request_id, "eof-reached", True)
    assert ended == [True]
    assert backend.status is PlaybackStatus.ENDED
    backend.close()
