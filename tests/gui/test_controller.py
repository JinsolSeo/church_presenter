from __future__ import annotations

from pathlib import Path

import fitz
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from church_presenter.domain.enums import ChannelRole, ContentType
from church_presenter.domain.models import AppSettings, Content, ScreenInfo, SubtitleStyle
from church_presenter.rendering.output_surface import OutputSurface
from church_presenter.services.screen_service import MockScreenService
from church_presenter.services.settings_service import SettingsService
from church_presenter.ui.controller_window import ControllerWindow


def make_controller(qtbot, tmp_path: Path) -> ControllerWindow:
    application = QApplication.instance()
    assert isinstance(application, QApplication)
    screens = MockScreenService([ScreenInfo("virtual", "CI Virtual", 0, 0, 1280, 720, 1.0, True)])
    settings = AppSettings(
        pdf_folder=str(tmp_path),
        simulation_mode=True,
        simulation_width=1280,
        simulation_height=720,
        simulation_dpr=2.0,
    )
    window = ControllerWindow(
        application,
        screens,  # type: ignore[arg-type]
        SettingsService(tmp_path / "settings"),
        settings,
    )
    qtbot.addWidget(window)
    window.show()
    return window


def create_pdf(path: Path, page_count: int = 3) -> None:
    document = fitz.open()
    for page_index in range(page_count):
        page = document.new_page(width=800, height=600)
        page.insert_text((72, 72), f"Page {page_index + 1}", fontsize=24)
    document.save(path)
    document.close()


def test_preview_selection_waits_for_take(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    content = Content.subtitle("Preview only", 0, SubtitleStyle(), "#00FF00")
    window.set_preview(ChannelRole.BROADCAST, content)
    assert window.state.broadcast.preview_content == content
    assert window.state.broadcast.live_content.kind is ContentType.BLACK
    qtbot.mouseClick(window.take_broadcast, Qt.MouseButton.LeftButton)
    assert window.state.broadcast.live_content == content


def test_take_normalizes_string_role_from_qt(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    assert window.take("broadcast") is True
    assert "Broadcast TAKE 완료" in window.status.text()
    window.pdf_panel.set_target_role(ChannelRole.VENUE)
    qtbot.mouseClick(window.pdf_panel.take_button, Qt.MouseButton.LeftButton)
    assert "Venue TAKE 완료" in window.status.text()


def test_simulation_mode_uses_real_output_surface(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    qtbot.mouseClick(window.start_outputs_button, Qt.MouseButton.LeftButton)
    assert window.broadcast_simulator is not None
    assert window.venue_simulator is not None
    assert isinstance(window.broadcast_simulator.surface, OutputSurface)
    assert isinstance(window.venue_simulator.surface, OutputSurface)
    assert window.broadcast_simulator.profile == (1280, 720)
    assert window.broadcast_simulator.surface.render_scale == 2.0
    window.stop_outputs()


def test_keyboard_navigation_does_not_steal_text_edit_keys(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    panel = window.subtitle_panel
    panel.document.lines = ["A", "B", "C"]
    panel.document.group_size = 1
    panel.preview_index = 0
    panel._refresh()
    panel.line_edit.setFocus()
    qtbot.keyClick(panel.line_edit, Qt.Key.Key_Right)
    assert panel.preview_index == 0
    window.setFocus()
    qtbot.keyClick(window, Qt.Key.Key_Right)
    assert panel.preview_index == 1


def test_close_turns_all_channels_black(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    content = Content.subtitle("Live", 0, SubtitleStyle(), "#00FF00")
    window.set_preview(ChannelRole.BROADCAST, content)
    window.take(ChannelRole.BROADCAST)
    window.close()
    assert window.state.broadcast.live_content.kind is ContentType.BLACK
    assert window.state.venue.live_content.kind is ContentType.BLACK


def test_linked_navigation_advances_subtitle_and_venue_pdf(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "linked.pdf"
    create_pdf(path)
    window = make_controller(qtbot, tmp_path)
    panel = window.subtitle_panel
    panel.document.lines = ["자막 1", "자막 2", "자막 3"]
    panel.document.group_size = 1
    panel.preview_index = 0
    panel._refresh()
    panel.navigate(0)
    qtbot.waitUntil(lambda: window.pdf_panel.file_list.count() == 1, timeout=5000)
    window.pdf_panel.set_target_role(ChannelRole.VENUE)
    window.pdf_panel.file_list.setCurrentRow(0)
    qtbot.waitUntil(lambda: window.pdf_panel.page_count == 3, timeout=5000)

    assert not window.sync_content_check.isChecked()
    qtbot.mouseClick(window.sync_next_button, Qt.MouseButton.LeftButton)
    assert window.sync_content_check.isChecked()
    assert window.pdf_panel.target_role is ChannelRole.VENUE
    assert panel.preview_index == 1
    assert window.pdf_panel.preview_page == 1
    assert "함께 이동" in window.status.text()
    qtbot.keyClick(window.sync_next_button, Qt.Key.Key_Left)
    assert panel.preview_index == 0
    assert window.pdf_panel.preview_page == 0
    qtbot.keyClick(window.sync_next_button, Qt.Key.Key_Right)
    assert window.state.broadcast.preview_content.kind is ContentType.SUBTITLE_KEY
    assert window.state.venue.preview_content.kind is ContentType.PDF_PAGE
    qtbot.waitUntil(lambda: window.state.venue.is_ready, timeout=10000)
    qtbot.keyClick(window.sync_next_button, Qt.Key.Key_Return)
    assert window.state.broadcast.live_content.kind is ContentType.SUBTITLE_KEY
    assert window.state.venue.live_content.kind is ContentType.PDF_PAGE
    assert panel.live_index == 1
    assert window.pdf_panel.live_pages[ChannelRole.VENUE] == 1


def test_focused_content_tab_keeps_individual_navigation(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "focus.pdf"
    create_pdf(path)
    window = make_controller(qtbot, tmp_path)
    panel = window.subtitle_panel
    panel.document.lines = ["자막 1", "자막 2", "자막 3"]
    panel.document.group_size = 1
    panel._refresh()
    panel.navigate(0)
    qtbot.waitUntil(lambda: window.pdf_panel.file_list.count() == 1, timeout=5000)
    window.pdf_panel.set_target_role(ChannelRole.VENUE)
    window.pdf_panel.file_list.setCurrentRow(0)
    qtbot.waitUntil(lambda: window.pdf_panel.page_count == 3, timeout=5000)

    window.sync_next_button.setFocus()
    qtbot.keyClick(window.sync_next_button, Qt.Key.Key_Right)
    assert panel.preview_index == 1
    assert window.pdf_panel.preview_page == 1
    assert window.sync_bar.property("keyboardActive") is True

    window.tabs.setCurrentWidget(panel)
    panel.card_list.setFocus()
    qtbot.keyClick(panel.card_list, Qt.Key.Key_Right)
    assert panel.preview_index == 2
    assert window.pdf_panel.preview_page == 1
    assert window.sync_bar.property("keyboardActive") is False

    window.tabs.setCurrentWidget(window.pdf_panel)
    window.pdf_panel.thumbnail_list.setFocus()
    qtbot.keyClick(window.pdf_panel.thumbnail_list, Qt.Key.Key_Left)
    assert panel.preview_index == 2
    assert window.pdf_panel.preview_page == 0


def test_linked_navigation_uses_each_preview_content_type(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "content-types.pdf"
    create_pdf(path)
    window = make_controller(qtbot, tmp_path)
    qtbot.waitUntil(lambda: window.pdf_panel.file_list.count() == 1, timeout=5000)
    window.pdf_panel.set_target_role(ChannelRole.BROADCAST)
    window.pdf_panel.file_list.setCurrentRow(0)
    qtbot.waitUntil(lambda: window.pdf_panel.page_count == 3, timeout=5000)
    assert window.state.broadcast.preview_content.kind is ContentType.PDF_PAGE
    assert window.state.venue.preview_content.kind is ContentType.BLACK

    window.sync_next_button.setFocus()
    qtbot.keyClick(window.sync_next_button, Qt.Key.Key_Right)
    assert window.state.broadcast.preview_content.pdf_page == 1
    assert window.state.venue.preview_content.kind is ContentType.BLACK

    window.pdf_panel.send_to_both()
    qtbot.keyClick(window.sync_next_button, Qt.Key.Key_Left)
    assert window.state.broadcast.preview_content.pdf_page == 0
    assert window.state.venue.preview_content.pdf_page == 0


def test_sync_checkbox_has_explicit_on_off_label(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    assert window.sync_content_check.objectName() == "SyncContentCheck"
    assert "꺼짐" in window.sync_content_check.text()
    window.sync_content_check.setChecked(True)
    assert "켜짐" in window.sync_content_check.text()
