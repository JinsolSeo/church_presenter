from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

from church_presenter.domain.enums import ChannelRole, ContentType, PauseReason, PlaybackStatus
from church_presenter.domain.models import AppSettings, Content, ScreenInfo
from church_presenter.media.mock_backend import MockMediaBackend
from church_presenter.rendering.output_surface import OutputSurface
from church_presenter.services.pdf_service import PdfRenderCoordinator
from church_presenter.services.screen_service import MockScreenService
from church_presenter.services.settings_service import SettingsService
from church_presenter.ui.controller_window import ControllerWindow


def make_media_controller(
    qtbot,
    tmp_path: Path,
    *,
    auto_frame: bool = True,
) -> tuple[ControllerWindow, list[MockMediaBackend]]:
    application = QApplication.instance()
    assert isinstance(application, QApplication)
    screens = MockScreenService([ScreenInfo("virtual", "CI Virtual", 0, 0, 1280, 720, 1.0, True)])
    video_backends: list[MockMediaBackend] = []

    def video_factory() -> MockMediaBackend:
        backend = MockMediaBackend(video=True, auto_frame=auto_frame)
        video_backends.append(backend)
        return backend

    settings = AppSettings(
        video_folder=str(tmp_path),
        audio_folder=str(tmp_path),
        simulation_mode=True,
        fade_duration_ms=20,
    )
    window = ControllerWindow(
        application,
        screens,  # type: ignore[arg-type]
        SettingsService(tmp_path / "settings"),
        settings,
        video_backend_factory=video_factory,
        audio_backend=MockMediaBackend(),
    )
    qtbot.addWidget(window)
    window.show()
    return window, video_backends


def test_video_take_waits_until_a_real_first_frame(qtbot, tmp_path: Path) -> None:
    video = tmp_path / "delayed.mp4"
    video.write_bytes(b"generated video")
    window, backends = make_media_controller(qtbot, tmp_path, auto_frame=False)
    panel = window.video_panel
    panel.selected_path = video
    panel.cue_selected()

    assert not window.state.broadcast.is_ready
    assert not panel.take_button.isEnabled()
    assert not panel.take_both_button.isEnabled()

    backends[0].emit_video_frame()
    qtbot.waitUntil(lambda: window.state.broadcast.is_ready, timeout=1000)
    assert panel.take_button.isEnabled()
    assert not panel.take_both_button.isEnabled()
    qtbot.mouseClick(panel.take_button, Qt.MouseButton.LeftButton)
    assert window.state.broadcast.live_content.kind is ContentType.VIDEO


def test_video_controls_are_compact_and_beside_library(qtbot, tmp_path: Path) -> None:
    window, _backends = make_media_controller(qtbot, tmp_path)
    window.preview_preset_dock.hide()
    window.tabs.setCurrentWidget(window.video_panel)
    QApplication.processEvents()
    panel = window.video_panel

    assert panel.control_panel.x() >= panel.file_list.geometry().right()
    assert panel.sizeHint().height() <= 380


def test_media_tabs_preserve_preview_and_content_heights(qtbot, tmp_path: Path) -> None:
    window, _backends = make_media_controller(qtbot, tmp_path)
    window.preview_preset_dock.hide()
    window.tabs.setCurrentIndex(0)
    QApplication.processEvents()
    expected_heights = (
        window.broadcast_preview.height(),
        window.content_scroll.height(),
    )

    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        QApplication.processEvents()
        assert abs(window.broadcast_preview.height() - expected_heights[0]) <= 1
        assert abs(window.content_scroll.height() - expected_heights[1]) <= 1


def test_non_video_preview_invalidates_video_take(qtbot, tmp_path: Path) -> None:
    video = tmp_path / "stale-take.mp4"
    video.write_bytes(b"generated video")
    window, _backends = make_media_controller(qtbot, tmp_path)
    panel = window.video_panel
    panel.selected_path = video
    panel.cue_selected()
    assert panel.take_button.isEnabled()

    window.set_preview(ChannelRole.BROADCAST, Content.black(), True)
    assert not panel.take_button.isEnabled()
    assert not window._take_video(ChannelRole.BROADCAST)
    assert window.state.broadcast.preview_content.kind is ContentType.BLACK


def test_video_stop_cannot_black_non_video_live(qtbot, tmp_path: Path) -> None:
    pdf = tmp_path / "live.pdf"
    pdf.write_bytes(b"generated pdf")
    window, _backends = make_media_controller(qtbot, tmp_path)
    window.state.broadcast.live_content = Content.pdf(pdf, 0)

    assert not window.video_manager.stop(ChannelRole.BROADCAST)
    assert window.state.broadcast.live_content.kind is ContentType.PDF_PAGE
    assert not window.video_panel.stop_button.isEnabled()


def test_video_click_cues_take_play_pause_and_stop_black(qtbot, tmp_path: Path) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"generated video")
    window, _backends = make_media_controller(qtbot, tmp_path)
    panel = window.video_panel
    qtbot.waitUntil(lambda: panel.file_list.count() == 1, timeout=3000)
    item_rect = panel.file_list.visualItemRect(panel.file_list.item(0))
    qtbot.mouseClick(
        panel.file_list.viewport(),
        Qt.MouseButton.LeftButton,
        pos=item_rect.center(),
    )
    qtbot.waitUntil(lambda: window.state.broadcast.is_ready, timeout=1000)
    assert window.state.broadcast.preview_content == Content.video(video)
    assert window.state.broadcast.live_content.kind is ContentType.BLACK
    assert "CUE" in panel.status_label.text()

    qtbot.mouseClick(panel.take_button, Qt.MouseButton.LeftButton)
    assert window.state.broadcast.live_content.kind is ContentType.VIDEO
    assert window.video_manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.LIVE_PAUSED
    qtbot.mouseClick(panel.play_button, Qt.MouseButton.LeftButton)
    assert window.video_manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.PLAYING
    qtbot.mouseClick(panel.pause_button, Qt.MouseButton.LeftButton)
    assert window.video_manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.PAUSED
    panel.seek_slider.sliderMoved.emit(3000)
    assert window.video_manager.runtime(ChannelRole.BROADCAST).position_ms == 3000
    panel.volume_slider.setValue(55)
    panel.mute_check.setChecked(True)
    assert window.video_manager.volume == 0.55
    assert window.video_manager.muted
    qtbot.mouseClick(panel.stop_button, Qt.MouseButton.LeftButton)
    assert window.state.broadcast.live_content.kind is ContentType.BLACK


def test_video_ended_and_error_each_turn_live_black(qtbot, tmp_path: Path) -> None:
    video = tmp_path / "events.mp4"
    video.write_bytes(b"generated video")
    window, backends = make_media_controller(qtbot, tmp_path)
    window.video_panel.selected_path = video
    window.video_panel.cue_selected()
    assert window.take(ChannelRole.BROADCAST)
    backends[0].finish()
    assert window.state.broadcast.live_content.kind is ContentType.BLACK

    window.video_panel.cue_selected()
    assert window.take(ChannelRole.BROADCAST)
    backends[1].fail("decoder failed")
    assert window.state.broadcast.live_content.kind is ContentType.BLACK
    assert "decoder failed" in window.status.text()


def test_video_send_take_both_and_simulation_uses_decoded_frame(qtbot, tmp_path: Path) -> None:
    video = tmp_path / "both.mp4"
    video.write_bytes(b"generated video")
    window, _backends = make_media_controller(qtbot, tmp_path)
    panel = window.video_panel
    panel.selected_path = video
    panel.cue_both()
    assert window.state.broadcast.is_ready
    assert window.state.venue.is_ready
    assert window.take_both()
    assert window.state.broadcast.live_content.kind is ContentType.VIDEO
    assert window.state.venue.live_content.kind is ContentType.VIDEO
    assert window.video_manager.is_live_transport_linked
    qtbot.mouseClick(panel.play_button, Qt.MouseButton.LeftButton)
    assert window.video_manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.PLAYING
    assert window.video_manager.runtime(ChannelRole.VENUE).status is PlaybackStatus.PLAYING
    window.start_outputs()
    assert window.broadcast_simulator is not None
    assert window.venue_simulator is not None
    assert isinstance(window.broadcast_simulator.surface, OutputSurface)
    qtbot.waitUntil(
        lambda: not window.broadcast_simulator.surface.video_frame.isNull(),
        timeout=1000,
    )
    assert not window.venue_simulator.surface.video_frame.isNull()


def test_video_play_marks_music_auto_pause_without_resume(qtbot, tmp_path: Path) -> None:
    video = tmp_path / "conflict.mp4"
    track = tmp_path / "music.wav"
    video.write_bytes(b"generated video")
    track.write_bytes(b"generated audio")
    window, _backends = make_media_controller(qtbot, tmp_path)
    window.audio_controller.add_paths([track])
    assert window.audio_controller.play()
    window.video_panel.selected_path = video
    window.video_panel.cue_selected()
    assert window.take(ChannelRole.BROADCAST)
    assert window.audio_controller.runtime.status is PlaybackStatus.PLAYING
    window.video_manager.play(ChannelRole.BROADCAST)
    assert window.audio_controller.runtime.status is PlaybackStatus.PAUSED
    assert window.audio_controller.runtime.pause_reason is PauseReason.VIDEO
    assert "영상 재생" in window.audio_panel.status_label.text()
    window.video_manager.stop(ChannelRole.BROADCAST)
    assert window.audio_controller.runtime.status is PlaybackStatus.PAUSED
    window.audio_controller.playlist.is_modified = False


def test_audio_device_disconnect_falls_back_to_system_default(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    window, video_backends = make_media_controller(qtbot, tmp_path)
    music_backend = window.audio_controller.backend
    assert isinstance(music_backend, MockMediaBackend)
    window.settings.audio_output_device_id = "external-speaker"
    assert window._apply_audio_output_device("external-speaker")

    monkeypatch.setattr(window.audio_device_service, "is_available", lambda _device_id: False)
    window._audio_outputs_changed()

    assert window.settings.audio_output_device_id == ""
    assert all(not backend.audio_output_device_id for backend in video_backends)
    assert not music_backend.audio_output_device_id
    assert "시스템 기본 출력" in window.status.text()


def test_audio_playlist_add_reorder_repeat_and_save_restore(qtbot, tmp_path: Path) -> None:
    tracks = [tmp_path / f"track-{index}.wav" for index in range(3)]
    for track in tracks:
        track.write_bytes(b"generated audio")
    window, _backends = make_media_controller(qtbot, tmp_path)
    panel = window.audio_panel
    window.audio_controller.add_paths(tracks)
    assert panel.playlist_list.count() == 3
    model = panel.playlist_list.model()
    assert model.moveRows(QModelIndex(), 0, 1, QModelIndex(), 3)
    assert window.audio_controller.playlist.items[2].path == tracks[0]
    panel.repeat_combo.setCurrentIndex(2)
    playlist_path = tmp_path / "saved-playlist.json"
    panel.save_playlist(playlist_path)
    window.audio_controller.clear()
    panel.load_playlist(playlist_path)
    assert len(window.audio_controller.playlist.items) == 3
    assert window.audio_controller.playlist.repeat_mode.value == "all"
    panel.playlist_list.setCurrentRow(0)
    qtbot.mouseClick(panel.play_button, Qt.MouseButton.LeftButton)
    assert window.audio_controller.runtime.status is PlaybackStatus.PLAYING
    panel.seek_slider.sliderMoved.emit(2000)
    assert window.audio_controller.runtime.position_ms == 2000
    qtbot.mouseClick(panel.pause_button, Qt.MouseButton.LeftButton)
    assert window.audio_controller.runtime.status is PlaybackStatus.PAUSED
    panel.volume_slider.setValue(45)
    panel.mute_check.setChecked(True)
    assert window.audio_controller.runtime.volume == 0.45
    assert window.audio_controller.runtime.is_muted
    qtbot.mouseClick(panel.stop_button, Qt.MouseButton.LeftButton)
    assert window.audio_controller.runtime.status is PlaybackStatus.STOPPED
    window.audio_controller.playlist.is_modified = False


def test_output_surface_fades_between_black_and_video(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "fade.mp4"
    path.write_bytes(b"generated video")
    surface = OutputSurface(PdfRenderCoordinator())
    qtbot.addWidget(surface)
    surface.show()
    content = Content.video(path)
    surface.set_content(content, 40)
    assert surface.target_content == content
    assert surface.content.kind is ContentType.BLACK
    qtbot.waitUntil(lambda: surface.content == content, timeout=1000)
    qtbot.waitUntil(lambda: surface._opacity == 1.0, timeout=1000)
