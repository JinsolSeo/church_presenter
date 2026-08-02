from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from church_presenter.domain.enums import (
    AudioSourceType,
    ChannelRole,
    ContentType,
    PauseReason,
    PlaybackStatus,
    SortField,
)
from church_presenter.domain.models import AppSettings, Content, ScreenInfo
from church_presenter.media.mock_backend import MockMediaBackend
from church_presenter.media.playlist import YOUTUBE_URL_FILENAME
from church_presenter.media.youtube_resolver import YouTubeMetadata
from church_presenter.rendering.output_surface import OutputSurface
from church_presenter.services.pdf_service import PdfRenderCoordinator
from church_presenter.services.screen_service import MockScreenService
from church_presenter.services.settings_service import SettingsService
from church_presenter.services.video_url_service import VideoUrlService
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

    control_x = panel.control_panel.mapTo(panel, QPoint()).x()
    assert control_x >= panel.file_list.geometry().right()
    assert panel.sizeHint().height() <= 380
    assert panel.take_button.property("heightRole") == "standard"
    assert panel.take_both_button.property("heightRole") == "standard"
    action_buttons = (
        panel.cue_button,
        panel.cue_both_button,
        panel.take_button,
        panel.take_both_button,
    )
    widths = {button.width() for button in action_buttons}
    assert max(widths) - min(widths) <= 1
    assert len({button.height() for button in action_buttons}) == 1
    assert panel.cue_button.x() < panel.cue_both_button.x()
    assert panel.cue_button.y() < panel.take_button.y()
    assert panel.action_panel.parentWidget() is panel.control_panel
    assert all(button.parentWidget() is panel.action_panel for button in action_buttons)
    assert not hasattr(panel, "sort_combo")
    assert not hasattr(panel, "descending_check")
    assert (
        abs(
            panel.refresh_button.geometry().right()
            - panel.file_list.geometry().right()
        )
        <= 1
    )
    assert all(
        button.height() <= 32
        for button in panel.control_panel.findChildren(QPushButton)
    )
    assert panel.target_combo.geometry().right() <= panel.width()
    assert (
        panel.action_panel.y() + panel.take_button.geometry().bottom()
        < panel.play_button.y()
    )
    assert panel.play_button.y() < panel.seek_slider.y()
    assert panel.seek_slider.geometry().bottom() <= panel.control_panel.contentsRect().bottom()
    assert panel.cue_button.property("variant") == "secondary"
    assert panel.cue_both_button.property("variant") == "primary"
    assert panel.take_button.property("variant") == "secondary"
    assert panel.take_both_button.property("variant") == "take"
    assert not hasattr(panel, "fade_spin")
    assert not hasattr(panel, "status_label")
    assert window.settings.fade_duration_ms == 250


def test_video_feature_update_button_starts_confirmed_venv_update(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    window, _backends = make_media_controller(qtbot, tmp_path)
    panel = window.video_panel
    starts: list[bool] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(panel.feature_updater, "start", lambda: starts.append(True))

    qtbot.mouseClick(panel.feature_update_button, Qt.MouseButton.LeftButton)

    assert starts == [True]
    assert panel.feature_update_button.text() == "기능 최신화"
    assert panel.feature_update_button.parentWidget() is panel.control_column


def test_video_library_is_always_newest_first(qtbot, tmp_path: Path) -> None:
    older = tmp_path / "older.mp4"
    newer = tmp_path / "newer.mp4"
    older.write_bytes(b"older")
    newer.write_bytes(b"newer")
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_800_000_000, 1_800_000_000))

    window, _backends = make_media_controller(qtbot, tmp_path)
    panel = window.video_panel
    qtbot.waitUntil(lambda: panel.file_list.count() == 2, timeout=3000)

    assert panel.sort_field is SortField.MODIFIED
    assert panel.descending is True
    assert not hasattr(panel, "sort_combo")
    assert not hasattr(panel, "descending_check")
    assert panel.file_list.item(0).text().startswith("newer.mp4")
    assert panel.file_list.item(1).text().startswith("older.mp4")


def test_video_panel_auto_loads_url_and_uses_local_video_workflow(
    qtbot,
    tmp_path: Path,
) -> None:
    url = "https://youtu.be/abc123"
    VideoUrlService().save(tmp_path, [url])
    window, _backends = make_media_controller(qtbot, tmp_path)
    panel = window.video_panel
    qtbot.waitUntil(lambda: panel.file_list.count() == 1, timeout=3000)

    item = panel.file_list.item(0)
    assert item.data(Qt.ItemDataRole.UserRole) == url
    panel.file_list.setCurrentItem(item)
    assert panel.selected_source == url
    assert panel.url_remove_button.isEnabled()

    qtbot.mouseClick(panel.cue_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.state.broadcast.is_ready, timeout=1000)
    assert panel.take_button.isEnabled()
    assert window.state.broadcast.preview_content.video_url == url

    qtbot.mouseClick(panel.take_button, Qt.MouseButton.LeftButton)
    assert window.state.broadcast.live_content.video_url == url
    assert panel.play_button.isEnabled()
    qtbot.mouseClick(panel.play_button, Qt.MouseButton.LeftButton)
    assert panel.manager.runtime(ChannelRole.BROADCAST).status is PlaybackStatus.PLAYING


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
    assert window.state.broadcast.preview_content.kind is ContentType.BLACK
    assert panel.cue_button.isEnabled()
    qtbot.mouseClick(panel.cue_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.state.broadcast.is_ready, timeout=1000)
    assert window.state.broadcast.preview_content == Content.video(video)
    assert window.state.broadcast.live_content.kind is ContentType.BLACK
    assert "Preview 준비 완료" in window.status.text()

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
    qtbot.waitUntil(lambda: len(window.audio_controller.playlist.items) == 1, timeout=1000)
    assert window.audio_controller.play()
    window.video_panel.selected_path = video
    window.video_panel.cue_selected()
    assert window.take(ChannelRole.BROADCAST)
    assert window.audio_controller.runtime.status is PlaybackStatus.PLAYING
    window.video_manager.play(ChannelRole.BROADCAST)
    assert window.audio_controller.runtime.status is PlaybackStatus.PAUSED
    assert window.audio_controller.runtime.pause_reason is PauseReason.VIDEO
    assert "영상 재생" in window.status.text()
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


def test_audio_folder_is_playlist_and_compact_player_is_on_right(qtbot, tmp_path: Path) -> None:
    tracks = [tmp_path / f"track-{index}.wav" for index in range(3)]
    for track in tracks:
        track.write_bytes(b"generated audio")
    window, _backends = make_media_controller(qtbot, tmp_path)
    panel = window.audio_panel
    window.tabs.setCurrentWidget(panel)
    QApplication.processEvents()
    qtbot.waitUntil(lambda: panel.playlist_list.count() == 3, timeout=1000)
    assert [item.path for item in window.audio_controller.playlist.items] == tracks
    assert panel.control_panel.x() > panel.playlist_box.x()
    assert panel.previous_button.text() == "⏮"
    assert panel.play_button.text() == "▶"
    assert panel.pause_button.text() == "⏸"
    assert panel.stop_button.text() == "■"
    assert panel.next_button.text() == "⏭"
    assert not hasattr(panel, "playlist_path")
    panel.repeat_combo.setCurrentIndex(2)
    assert len(window.audio_controller.playlist.items) == 3
    assert window.audio_controller.playlist.repeat_mode.value == "all"
    panel.playlist_list.setCurrentRow(0)
    qtbot.mouseClick(panel.play_button, Qt.MouseButton.LeftButton)
    assert window.audio_controller.runtime.status is PlaybackStatus.PLAYING
    assert panel.track_summary_label.text().startswith("track-0")
    assert panel.playback_summary_label.text() == "재생 중"
    assert (
        panel.track_summary_label.y()
        < panel.play_button.y()
        < panel.seek_slider.y()
        < panel.volume_slider.y()
    )
    assert panel.repeat_combo.geometry().bottom() <= panel.control_panel.contentsRect().bottom()
    expected_active = QColor(
        str(window.theme_manager.current_value("colors", "accent"))
    )
    expected_active_text = QColor(
        str(window.theme_manager.current_value("colors", "text_on_accent"))
    )
    assert panel.playlist_list.item(0).background().color() == expected_active
    assert panel.playlist_list.item(0).foreground().color() == expected_active_text
    panel.playlist_list.setCurrentRow(1)
    assert panel.playlist_list.item(0).background().color() == expected_active
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
    assert panel.playlist_list.item(0).background().color().alpha() == 0
    assert not hasattr(panel, "current_title_label")
    assert not hasattr(panel, "current_source_label")
    assert not hasattr(panel, "playback_state_label")
    assert not hasattr(panel, "status_label")
    window.audio_controller.playlist.is_modified = False


def test_audio_panel_adds_youtube_and_shows_metadata_state(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    window, _backends = make_media_controller(qtbot, tmp_path)
    panel = window.audio_panel
    monkeypatch.setattr(
        window.audio_controller.metadata_service,
        "request_metadata",
        lambda _request_id, _url: True,
    )
    monkeypatch.setattr(
        "church_presenter.ui.panels.audio_panel.QInputDialog.getText",
        lambda *_args, **_kwargs: ("https://youtu.be/abc123", True),
    )

    qtbot.mouseClick(panel.youtube_add_button, Qt.MouseButton.LeftButton)
    url_path = tmp_path / YOUTUBE_URL_FILENAME
    assert url_path.is_file()
    assert json.loads(url_path.read_text(encoding="utf-8"))["urls"] == [
        {"url": "https://youtu.be/abc123"}
    ]
    item = window.audio_controller.playlist.items[0]
    assert item.source_type is AudioSourceType.YOUTUBE
    assert "YOUTUBE" in panel.playlist_list.item(0).text()
    assert "unresolved" in panel.playlist_list.item(0).text()
    assert panel.fallback_button.isEnabled()

    window.audio_controller.metadata_service.resolved.emit(
        item.item_id,
        YouTubeMetadata("찬양 스트림", 90_000, "abc123", item.source),
    )
    assert "찬양 스트림" in panel.playlist_list.item(0).text()
    assert "01:30" in panel.playlist_list.item(0).text()

    window.audio_controller.metadata_service.failed.emit(item.item_id, "network unavailable")
    assert "unavailable" in panel.playlist_list.item(0).text()
    assert panel.retry_button.isEnabled()
    fallback = tmp_path / "fallback.wav"
    fallback.write_bytes(b"audio")
    monkeypatch.setattr(
        "church_presenter.ui.panels.audio_panel.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(fallback), "Audio"),
    )
    qtbot.mouseClick(panel.fallback_button, Qt.MouseButton.LeftButton)
    assert "fallback" in panel.playlist_list.item(0).text()
    saved_entry = json.loads(url_path.read_text(encoding="utf-8"))["urls"][0]
    assert saved_entry["fallback_path"] == "fallback.wav"
    qtbot.mouseClick(panel.remove_youtube_button, Qt.MouseButton.LeftButton)
    assert json.loads(url_path.read_text(encoding="utf-8"))["urls"] == []
    assert panel.playlist_list.count() == 0


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


def test_output_surface_renders_solid_blank_color(qtbot) -> None:
    surface = OutputSurface(PdfRenderCoordinator())
    qtbot.addWidget(surface)
    surface.resize(320, 180)
    surface.show()
    surface.set_content(Content.solid_color("#00FF00"))
    image = surface.grab().toImage()

    assert image.pixelColor(image.width() // 2, image.height() // 2) == QColor("#00FF00")
