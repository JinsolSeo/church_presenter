from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QVideoFrame

from church_presenter.domain.enums import ChannelRole, PlaybackStatus
from church_presenter.media.audio_controller import AudioPlaybackController
from church_presenter.media.qt_media_backend import QtMediaBackend
from church_presenter.media.video_manager import VideoPlaybackManager


@pytest.mark.media_integration
def test_qt_local_audio_first_play_stays_playing(qtbot) -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "sample_assets"
        / "audio"
        / "sample_track_01.wav"
    )
    backend = QtMediaBackend(video=False)
    controller = AudioPlaybackController(backend)
    controller.add_paths([path])

    assert controller.play(0)
    qtbot.waitUntil(
        lambda: controller.runtime.status is PlaybackStatus.PLAYING,
        timeout=5000,
    )
    qtbot.waitUntil(lambda: controller.runtime.position_ms >= 200, timeout=5000)
    assert backend.player.playbackState().name == "PlayingState"
    controller.close()


@pytest.mark.media_integration
def test_qt_backend_cues_first_frame_and_plays(qtbot) -> None:
    path = Path(__file__).resolve().parents[2] / "sample_assets" / "videos" / "sample_video.mp4"
    manager = VideoPlaybackManager(lambda: QtMediaBackend(video=True), muted=True)
    results: list[tuple[str, bool, str]] = []
    live_colors: list[int] = []
    live_frame_types: list[type[object]] = []

    def record_live_frame(_role: object, _path: str, frame: object) -> None:
        live_frame_types.append(type(frame))
        image = frame.toImage() if isinstance(frame, QVideoFrame) else frame
        if isinstance(image, QImage) and not image.isNull():
            live_colors.append(image.pixelColor(10, 10).rgb())

    manager.preview_result.connect(
        lambda _role, loaded_path, image, error: results.append(
            (loaded_path, image.isNull(), error)
        )
    )
    manager.live_frame_ready.connect(record_live_frame)
    manager.cue_preview(ChannelRole.BROADCAST, path)
    qtbot.waitUntil(lambda: bool(results), timeout=10_000)
    assert results[-1] == (str(path.resolve()), False, "")
    assert manager.activate_preview(ChannelRole.BROADCAST, path)
    assert manager.play(ChannelRole.BROADCAST)
    qtbot.waitUntil(
        lambda: manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.PLAYING,
        timeout=5000,
    )
    qtbot.waitUntil(
        lambda: manager.runtime(ChannelRole.BROADCAST).position_ms >= 500,
        timeout=5000,
    )
    qtbot.waitUntil(lambda: len(set(live_colors)) >= 2, timeout=5000)
    assert QVideoFrame in live_frame_types
    manager.pause(ChannelRole.BROADCAST)
    manager.stop(ChannelRole.BROADCAST)
    manager.close()


@pytest.mark.media_integration
def test_qt_backend_cues_both_then_recues_same_source(qtbot) -> None:
    path = Path(__file__).resolve().parents[2] / "sample_assets" / "videos" / "sample_video.mp4"
    manager = VideoPlaybackManager(lambda: QtMediaBackend(video=True), muted=True)
    results: list[tuple[ChannelRole, str, bool, str]] = []
    manager.preview_result.connect(
        lambda role, loaded_path, image, error: results.append(
            (role, loaded_path, image.isNull(), error)
        )
    )

    manager.cue_both(path)
    qtbot.waitUntil(
        lambda: {result[0] for result in results}
        == {ChannelRole.BROADCAST, ChannelRole.VENUE},
        timeout=10_000,
    )
    results.clear()
    manager.cue_preview(ChannelRole.BROADCAST, path)
    qtbot.waitUntil(
        lambda: any(result[0] is ChannelRole.BROADCAST for result in results),
        timeout=10_000,
    )
    role, loaded_path, is_null, error = results[-1]
    assert (role, loaded_path, is_null, error) == (
        ChannelRole.BROADCAST,
        str(path.resolve()),
        False,
        "",
    )
    assert manager.preview_runtime(role).status is PlaybackStatus.CUE
    manager.close()


@pytest.mark.media_integration
def test_qt_linked_transport_plays_both_live_channels(qtbot) -> None:
    path = Path(__file__).resolve().parents[2] / "sample_assets" / "videos" / "sample_video.mp4"
    manager = VideoPlaybackManager(lambda: QtMediaBackend(video=True), muted=True)
    ready: set[ChannelRole] = set()
    manager.preview_result.connect(
        lambda role, _path, image, error: ready.add(role)
        if not error and not image.isNull()
        else None
    )
    manager.cue_both(path)
    qtbot.waitUntil(lambda: len(ready) == 2, timeout=10_000)
    assert manager.activate_preview(ChannelRole.BROADCAST, path)
    assert manager.activate_preview(ChannelRole.VENUE, path)
    assert manager.link_live_pair()

    assert manager.play(ChannelRole.BROADCAST)
    qtbot.waitUntil(
        lambda: all(
            manager.runtime(role).position_ms >= 500
            for role in (ChannelRole.BROADCAST, ChannelRole.VENUE)
        ),
        timeout=5000,
    )
    assert manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.PLAYING
    assert manager.runtime(ChannelRole.VENUE).status is PlaybackStatus.PLAYING
    manager.pause(ChannelRole.VENUE)
    assert manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.PAUSED
    assert manager.runtime(ChannelRole.VENUE).status is PlaybackStatus.PAUSED
    manager.close()
