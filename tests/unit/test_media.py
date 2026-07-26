from __future__ import annotations

from pathlib import Path

from church_presenter.domain.enums import (
    ChannelRole,
    ContentType,
    MediaType,
    PauseReason,
    PlaybackStatus,
    RepeatMode,
    SortField,
)
from church_presenter.domain.models import AudioPlaylist, Content, PlaylistItem
from church_presenter.domain.state import ApplicationState
from church_presenter.media.audio_controller import AudioPlaybackController
from church_presenter.media.base import MediaPlaybackBackend
from church_presenter.media.mock_backend import MockMediaBackend
from church_presenter.media.playlist import PlaylistService
from church_presenter.media.qt_media_backend import QtMediaBackend
from church_presenter.media.video_manager import VideoPlaybackManager
from church_presenter.services.file_library_service import scan_library, sort_items
from church_presenter.services.transition_service import (
    FIXED_OUTPUT_FADE_DURATION_MS,
    TransitionService,
)


def media_file(path: Path, content: bytes = b"generated") -> Path:
    path.write_bytes(content)
    return path


def test_video_and_audio_extension_filters(tmp_path: Path) -> None:
    media_file(tmp_path / "b.MP4")
    media_file(tmp_path / "a.mkv")
    media_file(tmp_path / "track.FLAC")
    media_file(tmp_path / "ignored.webm")
    videos = scan_library(tmp_path, MediaType.VIDEO)
    audio = scan_library(tmp_path, MediaType.AUDIO)
    assert {item.path.name for item in videos} == {"a.mkv", "b.MP4"}
    assert [item.path.name for item in audio] == ["track.FLAC"]
    assert [item.path.name for item in sort_items(videos, SortField.NAME)] == [
        "a.mkv",
        "b.MP4",
    ]


def test_video_content_take_and_missing_validation(tmp_path: Path) -> None:
    path = media_file(tmp_path / "service.mp4")
    state = ApplicationState()
    content = Content.video(path)
    state.set_preview(ChannelRole.BROADCAST, content)
    assert state.broadcast.live_content == Content.black()
    assert state.take(ChannelRole.BROADCAST) == (True, "")
    assert state.broadcast.live_content == content
    state.set_preview(ChannelRole.VENUE, Content.video(tmp_path / "missing.mp4"))
    assert state.take(ChannelRole.VENUE)[0] is False


def test_video_content_normalizes_relative_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    path = media_file(tmp_path / "relative.mp4")
    assert Content.video(Path("relative.mp4")).video_path == path.resolve()


def make_video_manager() -> tuple[VideoPlaybackManager, list[MockMediaBackend]]:
    backends: list[MockMediaBackend] = []

    def factory() -> MockMediaBackend:
        backend = MockMediaBackend(video=True)
        backends.append(backend)
        return backend

    return VideoPlaybackManager(factory), backends


def test_video_cue_take_play_pause_and_active_count(tmp_path: Path) -> None:
    path = media_file(tmp_path / "cue.mp4")
    manager, _backends = make_video_manager()
    results: list[tuple[ChannelRole, str]] = []
    manager.preview_result.connect(
        lambda role, loaded_path, _image, error: results.append((role, error or loaded_path))
    )
    manager.cue_preview(ChannelRole.BROADCAST, path)
    assert results[-1] == (ChannelRole.BROADCAST, str(path.resolve()))
    assert manager.can_activate(ChannelRole.BROADCAST, path)
    assert manager.activate_preview(ChannelRole.BROADCAST, path)
    assert manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.LIVE_PAUSED
    assert manager.play(ChannelRole.BROADCAST)
    assert manager.active_count == 1
    manager.pause(ChannelRole.BROADCAST)
    assert manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.PAUSED
    assert manager.active_count == 0


def test_video_recue_same_path_replaces_live_decoder(tmp_path: Path) -> None:
    path = media_file(tmp_path / "same.mp4")
    manager, backends = make_video_manager()
    manager.cue_preview(ChannelRole.BROADCAST, path)
    assert manager.activate_preview(ChannelRole.BROADCAST, path)
    assert manager.play(ChannelRole.BROADCAST)

    manager.cue_preview(ChannelRole.BROADCAST, path)
    assert manager.can_activate(ChannelRole.BROADCAST, path)
    assert manager.activate_preview(ChannelRole.BROADCAST, path)
    assert backends[0].status is PlaybackStatus.STOPPED
    assert manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.LIVE_PAUSED
    assert manager.play(ChannelRole.BROADCAST)
    assert backends[1].status is PlaybackStatus.PLAYING


def test_video_preview_error_clears_previous_readiness(tmp_path: Path) -> None:
    path = media_file(tmp_path / "error-after-cue.mp4")
    manager, backends = make_video_manager()
    manager.cue_preview(ChannelRole.BROADCAST, path)
    assert manager.can_activate(ChannelRole.BROADCAST, path)

    backends[0].fail("decoder failed after cue")
    assert not manager.can_activate(ChannelRole.BROADCAST, path)
    assert manager.preview_runtime(ChannelRole.BROADCAST).status is PlaybackStatus.ERROR


def test_video_controls_ignore_channel_without_live_video() -> None:
    manager, _backends = make_video_manager()
    stopped: list[ChannelRole] = []
    manager.live_stopped.connect(stopped.append)

    assert not manager.play(ChannelRole.BROADCAST)
    assert not manager.stop(ChannelRole.BROADCAST)
    manager.pause(ChannelRole.BROADCAST)
    manager.seek(ChannelRole.BROADCAST, 1000)
    assert stopped == []


def test_video_linked_transport_controls_both_live_channels(tmp_path: Path) -> None:
    path = media_file(tmp_path / "linked.mp4")
    manager, _backends = make_video_manager()
    stopped: list[ChannelRole] = []
    manager.live_stopped.connect(stopped.append)
    manager.cue_both(path)
    assert manager.activate_preview(ChannelRole.BROADCAST, path)
    assert manager.activate_preview(ChannelRole.VENUE, path)
    assert manager.link_live_pair()
    assert manager.is_live_transport_linked
    assert not _backends[0].muted
    assert _backends[2].muted

    assert manager.play(ChannelRole.BROADCAST)
    assert manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.PLAYING
    assert manager.runtime(ChannelRole.VENUE).status is PlaybackStatus.PLAYING
    manager.seek(ChannelRole.VENUE, 2500)
    assert manager.runtime(ChannelRole.BROADCAST).position_ms == 2500
    assert manager.runtime(ChannelRole.VENUE).position_ms == 2500
    manager.pause(ChannelRole.VENUE)
    assert manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.PAUSED
    assert manager.runtime(ChannelRole.VENUE).status is PlaybackStatus.PAUSED
    assert manager.stop(ChannelRole.BROADCAST)
    assert stopped == [ChannelRole.BROADCAST, ChannelRole.VENUE]
    assert not manager.is_live_transport_linked


def test_single_video_take_unlinks_both_transport(tmp_path: Path) -> None:
    first = media_file(tmp_path / "linked-first.mp4")
    replacement = media_file(tmp_path / "replacement.mp4")
    manager, _backends = make_video_manager()
    manager.cue_both(first)
    assert manager.activate_preview(ChannelRole.BROADCAST, first)
    assert manager.activate_preview(ChannelRole.VENUE, first)
    assert manager.link_live_pair()

    manager.cue_preview(ChannelRole.BROADCAST, replacement)
    assert manager.activate_preview(ChannelRole.BROADCAST, replacement)
    assert not manager.is_live_transport_linked
    assert not _backends[2].muted
    assert manager.play(ChannelRole.BROADCAST)
    assert manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.PLAYING
    assert manager.runtime(ChannelRole.VENUE).status is PlaybackStatus.LIVE_PAUSED


def test_video_take_both_partial_prepare_failure_preserves_state(tmp_path: Path) -> None:
    path = media_file(tmp_path / "both.mp4")
    manager, backends = make_video_manager()
    backends[2].fail_paths.add(path.resolve())
    state = ApplicationState()
    content = Content.video(path)
    state.set_preview(ChannelRole.BROADCAST, content, ready=False)
    state.set_preview(ChannelRole.VENUE, content, ready=False)

    def result(role: ChannelRole, _path: str, _image: object, error: str) -> None:
        state.mark_preview_ready(role, not error, error)

    manager.preview_result.connect(result)
    manager.cue_both(path)
    before = (state.broadcast.live_content, state.venue.live_content)
    assert state.take_both()[0] is False
    assert (state.broadcast.live_content, state.venue.live_content) == before


def test_video_stop_end_and_error_signals(tmp_path: Path) -> None:
    path = media_file(tmp_path / "events.mp4")
    manager, _backends = make_video_manager()
    stopped: list[ChannelRole] = []
    ended: list[ChannelRole] = []
    errors: list[str] = []
    manager.live_stopped.connect(stopped.append)
    manager.live_ended.connect(ended.append)
    manager.live_error.connect(lambda _role, message: errors.append(message))
    manager.cue_preview(ChannelRole.BROADCAST, path)
    manager.activate_preview(ChannelRole.BROADCAST, path)
    manager.stop(ChannelRole.BROADCAST)
    assert stopped == [ChannelRole.BROADCAST]
    live_backend = _backends[0]
    live_backend.finish()
    live_backend.fail("decoder failed")
    assert ended == [ChannelRole.BROADCAST]
    assert errors == ["decoder failed"]


def test_playlist_edit_index_and_previous_policy(tmp_path: Path) -> None:
    items = [
        PlaylistItem(str(index), media_file(tmp_path / f"{index}.wav"), f"Track {index}")
        for index in range(3)
    ]
    playlist = AudioPlaylist(items=items, current_index=1)
    playlist.move(1, 2)
    assert playlist.current_index == 2
    assert playlist.previous_index(4000) == 2
    assert playlist.previous_index(1000) == 1
    playlist.remove(1)
    assert playlist.current_index == 1
    playlist.clear()
    assert playlist.current_index is None


def test_playlist_repeat_policies(tmp_path: Path) -> None:
    items = [
        PlaylistItem(str(index), media_file(tmp_path / f"repeat-{index}.wav"), str(index))
        for index in range(2)
    ]
    playlist = AudioPlaylist(items=items, current_index=1)
    assert playlist.next_index(ended=True) is None
    playlist.repeat_mode = RepeatMode.ONE
    assert playlist.next_index(ended=True) == 1
    playlist.repeat_mode = RepeatMode.ALL
    assert playlist.next_index(ended=True) == 0


def test_playlist_json_round_trip_and_deleted_file(tmp_path: Path) -> None:
    track = media_file(tmp_path / "track.wav")
    playlist = AudioPlaylist(
        name="Service",
        items=[PlaylistItem("stable", track, "Track")],
        current_index=0,
        repeat_mode=RepeatMode.ALL,
        is_modified=True,
    )
    path = tmp_path / "playlist.json"
    service = PlaylistService()
    service.save(playlist, path)
    loaded = service.load(path)
    assert loaded.repeat_mode is RepeatMode.ALL
    assert loaded.current_item is not None
    assert loaded.current_item.path == track
    assert not loaded.is_modified
    track.unlink()
    unavailable = service.load(path).items[0]
    assert not unavailable.is_available
    assert unavailable.error_message


def test_audio_auto_next_repeat_and_previous(tmp_path: Path) -> None:
    first = media_file(tmp_path / "first.wav")
    second = media_file(tmp_path / "second.wav")
    backend = MockMediaBackend()
    controller = AudioPlaybackController(backend)
    controller.add_paths([first, second])
    assert controller.play(0)
    backend.finish()
    assert controller.playlist.current_index == 1
    assert controller.runtime.status is PlaybackStatus.PLAYING
    controller.set_repeat_mode(RepeatMode.ONE)
    backend.finish()
    assert controller.playlist.current_index == 1
    assert backend.position_ms == 0
    backend.seek(4000)
    controller.previous()
    assert controller.playlist.current_index == 1
    assert backend.position_ms == 0


def test_audio_restore_cues_position_without_playing(tmp_path: Path) -> None:
    track = media_file(tmp_path / "restore.wav")
    backend = MockMediaBackend()
    controller = AudioPlaybackController(backend)
    controller.add_paths([track])
    assert controller.cue_current(2500)
    assert controller.runtime.status is PlaybackStatus.CUE
    assert controller.runtime.position_ms == 2500
    assert backend.status is PlaybackStatus.READY


def test_missing_audio_switch_stops_previous_track_and_reports_selected_item(
    tmp_path: Path,
) -> None:
    playable = media_file(tmp_path / "playable.wav")
    missing = tmp_path / "missing.wav"
    backend = MockMediaBackend()
    controller = AudioPlaybackController(backend)
    controller.add_paths([playable, missing])

    assert controller.play(0)
    assert backend.status is PlaybackStatus.PLAYING
    assert not controller.play(1)

    assert backend.status is PlaybackStatus.STOPPED
    assert controller.runtime.status is PlaybackStatus.ERROR
    assert controller.runtime.title == "missing"
    assert controller.runtime.position_ms == 0
    assert "찾을 수 없습니다" in controller.runtime.error_message


def test_clearing_audio_playlist_removes_stale_runtime_metadata(tmp_path: Path) -> None:
    track = media_file(tmp_path / "clear-me.wav")
    controller = AudioPlaybackController(MockMediaBackend())
    controller.add_paths([track])
    assert controller.play()

    controller.clear()

    assert controller.runtime.status is PlaybackStatus.STOPPED
    assert controller.runtime.title == ""
    assert controller.runtime.source == ""
    assert controller.runtime.path is None
    assert controller.runtime.duration_ms == 0


def test_shared_audio_output_applies_to_all_video_and_music_backends() -> None:
    manager, video_backends = make_video_manager()
    music_backend = MockMediaBackend()
    audio = AudioPlaybackController(music_backend)

    assert manager.set_audio_output_device("external-speaker")
    assert audio.set_audio_output_device("external-speaker")
    assert all(
        backend.audio_output_device_id == "external-speaker"
        for backend in video_backends
    )
    assert music_backend.audio_output_device_id == "external-speaker"

    assert manager.set_audio_output_device("")
    assert audio.set_audio_output_device("")
    assert all(not backend.audio_output_device_id for backend in video_backends)
    assert not music_backend.audio_output_device_id


def test_video_play_pauses_music_only_at_play(tmp_path: Path) -> None:
    track = media_file(tmp_path / "music.wav")
    video = media_file(tmp_path / "video.mp4")
    audio = AudioPlaybackController(MockMediaBackend())
    audio.add_paths([track])
    assert audio.play()
    manager, _backends = make_video_manager()
    manager.play_started.connect(lambda _role: audio.pause_for_video())
    manager.cue_preview(ChannelRole.BROADCAST, video)
    assert audio.runtime.status is PlaybackStatus.PLAYING
    manager.activate_preview(ChannelRole.BROADCAST, video)
    assert audio.runtime.status is PlaybackStatus.PLAYING
    manager.play(ChannelRole.BROADCAST)
    assert audio.runtime.status is PlaybackStatus.PAUSED
    assert audio.runtime.pause_reason is PauseReason.VIDEO
    manager.stop(ChannelRole.BROADCAST)
    assert audio.runtime.status is PlaybackStatus.PAUSED


def test_transition_policy_and_backend_contract() -> None:
    assert FIXED_OUTPUT_FADE_DURATION_MS == 250
    assert TransitionService().fade_duration_ms == 250
    transition = TransitionService(5000)
    assert transition.fade_duration_ms == 2000
    assert transition.should_fade(Content.black().kind, ContentType.PDF_PAGE)
    assert not transition.should_fade(ContentType.SUBTITLE_KEY, ContentType.BLACK)
    for backend_type in (MockMediaBackend, QtMediaBackend):
        assert issubclass(backend_type, MediaPlaybackBackend)
        for method in (
            "load",
            "play",
            "pause",
            "stop",
            "seek",
            "set_volume",
            "set_muted",
            "set_audio_output_device",
            "close",
        ):
            assert callable(getattr(backend_type, method))
