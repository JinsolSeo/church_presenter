from __future__ import annotations

from pathlib import Path

import fitz
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog

from church_presenter.domain.enums import ChannelRole, ContentType
from church_presenter.domain.models import (
    AppSettings,
    Content,
    PreviewPreset,
    ScreenInfo,
    SubtitleStyle,
)
from church_presenter.rendering.output_surface import OutputSurface
from church_presenter.services.screen_service import MockScreenService
from church_presenter.services.settings_service import SettingsService
from church_presenter.ui.controller_window import ControllerWindow
from church_presenter.ui.styles import apply_application_style


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
    window.subtitle_panel.take_requested.emit()
    assert window.state.broadcast.live_content == content
    assert window.broadcast_simulator is not None
    assert window.broadcast_simulator.surface.target_content == content


def test_named_preview_preset_applies_without_changing_live(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    window.subtitle_panel.document.lines = ["찬양"]
    window.subtitle_panel.document.group_size = 1
    broadcast = Content.subtitle("찬양", 0, SubtitleStyle(), "#00FF00")
    venue = Content.black()
    window.set_preview(ChannelRole.BROADCAST, broadcast)
    window.set_preview(ChannelRole.VENUE, venue)
    window.preview_preset_panel.name_edit.setText("1. 찬양")

    qtbot.mouseClick(
        window.preview_preset_panel.save_button,
        Qt.MouseButton.LeftButton,
    )
    assert [preset.name for preset in window.preview_presets] == ["1. 찬양"]
    assert window.preview_presets[0].broadcast_content.text == ""
    assert window.settings_service.preview_presets_path.is_file()

    window.set_preview(ChannelRole.BROADCAST, Content.black())
    qtbot.mouseClick(
        window.preview_preset_panel.preset_buttons["1. 찬양"],
        Qt.MouseButton.LeftButton,
    )
    assert window.state.broadcast.preview_content == broadcast
    assert window.state.venue.preview_content == venue
    assert window.state.broadcast.live_content.kind is ContentType.BLACK
    assert window.state.venue.live_content.kind is ContentType.BLACK
    assert window.sync_bar.property("keyboardActive") is True
    assert not hasattr(window.preview_preset_panel, "take_both_button")

    qtbot.mouseClick(
        window.sync_take_button,
        Qt.MouseButton.LeftButton,
    )
    assert window.state.broadcast.live_content == broadcast
    assert window.state.venue.live_content == venue


def test_preview_preset_can_be_renamed_and_reordered(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    window.save_preview_preset("첫 순서")
    window.save_preview_preset("둘째 순서")

    assert window.move_preview_preset("둘째 순서", -1)
    assert window.rename_preview_preset("둘째 순서", "예배 시작")
    assert [preset.name for preset in window.preview_presets] == ["예배 시작", "첫 순서"]

    loaded, warning = window.settings_service.load_preview_presets()
    assert warning == ""
    assert [preset.name for preset in loaded] == ["예배 시작", "첫 순서"]


def test_row_save_is_temporary_until_saved_as(
    qtbot,
    tmp_path: Path,
) -> None:
    path = tmp_path / "이번주.pdf"
    create_pdf(path, page_count=4)
    window = make_controller(qtbot, tmp_path)
    qtbot.waitUntil(lambda: window.pdf_panel.file_list.count() == 1, timeout=5000)
    window.pdf_panel.file_list.setCurrentRow(0)
    qtbot.waitUntil(lambda: window.pdf_panel.page_count == 4, timeout=5000)
    initial = [
        PreviewPreset(
            "예배 시작",
            Content(kind=ContentType.PDF_PAGE, pdf_page=0),
            Content.black(),
        ),
        PreviewPreset("찬양", Content.black(), Content.black()),
    ]
    window.preview_presets = initial
    window.preview_preset_panel.set_presets(initial)
    order_path = tmp_path / "수정할_예배_순서.json"
    assert window.save_preview_preset_file(order_path)

    qtbot.mouseClick(
        window.preview_preset_panel.preset_buttons["예배 시작"],
        Qt.MouseButton.LeftButton,
    )
    qtbot.waitUntil(lambda: window.state.broadcast.is_ready, timeout=10000)
    window.pdf_panel.navigate_for_roles(2, (ChannelRole.BROADCAST,))
    qtbot.waitUntil(
        lambda: window.state.broadcast.is_ready
        and window.state.broadcast.preview_content.pdf_page == 2,
        timeout=10000,
    )
    live_before = (
        window.state.broadcast.live_content,
        window.state.venue.live_content,
    )

    qtbot.mouseClick(
        window.preview_preset_panel.update_buttons["예배 시작"],
        Qt.MouseButton.LeftButton,
    )

    assert [preset.name for preset in window.preview_presets] == ["예배 시작", "찬양"]
    assert window.preview_presets[0].broadcast_content.pdf_page == 2
    assert window.preview_presets[0].venue_content.kind is ContentType.BLACK
    assert window.preview_preset_panel.preset_buttons["예배 시작"].isChecked()
    assert (
        window.state.broadcast.live_content,
        window.state.venue.live_content,
    ) == live_before
    original = window.settings_service.load_preview_preset_file(order_path)
    assert original[0].broadcast_content.pdf_page == 0

    revised_path = tmp_path / "수정된_예배_순서.json"
    assert window.save_preview_preset_file(revised_path)
    revised = window.settings_service.load_preview_preset_file(revised_path)
    assert revised == window.preview_presets


def test_pdf_preview_preset_waits_for_high_resolution_prepare(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "preset.pdf"
    create_pdf(path, page_count=2)
    window = make_controller(qtbot, tmp_path)
    qtbot.waitUntil(lambda: window.pdf_panel.file_list.count() == 1, timeout=5000)
    window.pdf_panel.file_list.setCurrentRow(0)
    qtbot.waitUntil(lambda: window.pdf_panel.page_count == 2, timeout=5000)
    preset = PreviewPreset(
        "말씀",
        Content(kind=ContentType.PDF_PAGE, pdf_page=1),
        Content.black(),
    )
    window.preview_presets = [preset]
    window.preview_preset_panel.set_presets([preset])

    assert window.apply_preview_preset("말씀")
    assert not window.state.broadcast.is_ready
    assert not window.sync_take_button.isEnabled()
    assert window.sync_bar.property("keyboardActive") is True
    assert window.state.broadcast.live_content.kind is ContentType.BLACK
    qtbot.waitUntil(lambda: window.state.broadcast.is_ready, timeout=10000)

    assert window.sync_take_button.isEnabled()
    assert window.state.broadcast.preview_content == Content.pdf(path, 1)
    assert window.state.broadcast.live_content.kind is ContentType.BLACK


def test_unavailable_preview_preset_preserves_existing_previews(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    before_broadcast = Content.subtitle("유지", 0, SubtitleStyle(), "#00FF00")
    before_venue = Content.black()
    window.set_preview(ChannelRole.BROADCAST, before_broadcast)
    window.set_preview(ChannelRole.VENUE, before_venue)
    preset = PreviewPreset(
        "삭제된 파일",
        Content.pdf(tmp_path / "missing.pdf", 0),
        Content.black(),
    )
    window.preview_presets = [preset]

    assert not window.apply_preview_preset("삭제된 파일")
    assert window.state.broadcast.preview_content == before_broadcast
    assert window.state.venue.preview_content == before_venue
    assert "기존 Preview 유지" in window.status.text()


def test_worship_order_changes_stay_temporary_until_saved_as(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    window.save_preview_preset("예배 시작")
    order_path = tmp_path / "주일_예배_순서.json"

    assert window.save_preview_preset_file(order_path)
    assert window.preview_preset_file == order_path.resolve()
    assert window.preview_preset_panel.file_label.text() == (
        f"기준 파일 · {order_path.name} · JSON 저장은 다른 이름"
    )
    assert window.preview_preset_panel.file_label.toolTip() == str(order_path.resolve())
    assert window.settings.preview_preset_file == str(order_path.resolve())

    window.save_preview_preset("찬양")
    saved = window.settings_service.load_preview_preset_file(order_path)
    assert [preset.name for preset in saved] == ["예배 시작"]

    revised_path = tmp_path / "주일_예배_순서_수정본.json"
    assert window.save_preview_preset_file(revised_path)
    revised = window.settings_service.load_preview_preset_file(revised_path)
    assert [preset.name for preset in revised] == ["예배 시작", "찬양"]

    replacement_path = tmp_path / "저녁_예배_순서.json"
    replacement = [PreviewPreset("저녁 예배", Content.black(), Content.black())]
    window.settings_service.save_preview_preset_file(replacement_path, replacement)
    assert window.load_preview_preset_file(replacement_path)
    assert window.preview_presets == replacement
    assert window.settings_service.load_preview_presets()[0] == replacement


def test_loaded_order_resets_list_and_uses_current_documents(qtbot, tmp_path: Path) -> None:
    current_pdf = tmp_path / "이번주.pdf"
    create_pdf(current_pdf, page_count=4)
    window = make_controller(qtbot, tmp_path)
    window.save_preview_preset("기존 항목")
    window.subtitle_panel.document.lines = ["이번 주 첫 자막", "이번 주 둘째 자막"]
    window.subtitle_panel.document.group_size = 1
    qtbot.waitUntil(lambda: window.pdf_panel.file_list.count() == 1, timeout=5000)
    window.pdf_panel.file_list.setCurrentRow(0)
    qtbot.waitUntil(lambda: window.pdf_panel.page_count == 4, timeout=5000)
    order_path = tmp_path / "위치_기준_예배_순서.json"
    order = [
        PreviewPreset(
            "말씀 시작",
            Content(kind=ContentType.SUBTITLE_KEY, subtitle_card_index=1),
            Content(kind=ContentType.PDF_PAGE, pdf_page=2),
        )
    ]
    window.settings_service.save_preview_preset_file(order_path, order)

    assert window.load_preview_preset_file(order_path)
    assert window.preview_presets == order
    assert "기존 항목" not in window.preview_preset_panel.preset_buttons
    assert set(window.preview_preset_panel.preset_buttons) == {"말씀 시작"}
    assert window.apply_preview_preset("말씀 시작")

    assert window.state.broadcast.preview_content.text == "이번 주 둘째 자막"
    assert window.state.broadcast.preview_content.subtitle_card_index == 1
    assert window.state.venue.preview_content.pdf_path == current_pdf
    assert window.state.venue.preview_content.pdf_page == 2
    assert window.subtitle_panel.preview_index == 1
    assert window.pdf_panel.preview_page == 2


def test_worship_order_file_buttons_use_selected_json(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    window = make_controller(qtbot, tmp_path)
    assert not hasattr(window.preview_preset_panel, "save_file_button")
    window.save_preview_preset("저장할 순서")
    saved_path = tmp_path / "버튼_저장.json"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(saved_path), "JSON"),
    )

    qtbot.mouseClick(
        window.preview_preset_panel.save_file_as_button,
        Qt.MouseButton.LeftButton,
    )
    assert saved_path.is_file()

    replacement_path = tmp_path / "버튼_불러오기.json"
    replacement = [PreviewPreset("불러온 순서", Content.black(), Content.black())]
    window.settings_service.save_preview_preset_file(replacement_path, replacement)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(replacement_path), "JSON"),
    )

    qtbot.mouseClick(
        window.preview_preset_panel.open_file_button,
        Qt.MouseButton.LeftButton,
    )
    assert window.preview_presets == replacement
    assert set(window.preview_preset_panel.preset_buttons) == {"불러온 순서"}


def test_compact_controller_layout_uses_tab_take_controls(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)

    assert not hasattr(window, "take_broadcast")
    assert not hasattr(window, "take_venue")
    assert window.status.parentWidget() is window.statusBar()
    assert window.root_scroll.widget().layout().indexOf(window.status) == -1


def test_compact_controller_fits_without_vertical_scroll(qtbot, tmp_path: Path) -> None:
    application = QApplication.instance()
    assert isinstance(application, QApplication)
    apply_application_style(application)
    window = make_controller(qtbot, tmp_path)
    window.resize(900, 760)
    qtbot.wait(20)

    assert window.root_scroll.horizontalScrollBar().maximum() == 0
    assert window.root_scroll.verticalScrollBar().maximum() == 0
    assert window.subtitle_panel.file_label.width() > 0


def test_controller_gives_more_extra_height_to_monitors(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    root_layout = window.root_scroll.widget().layout()

    assert root_layout.stretch(1) == 3
    assert root_layout.stretch(3) == 2


def test_controller_geometry_is_clamped_to_available_screen(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    screen = window.screen()
    assert screen is not None
    available = screen.availableGeometry()

    window.hide()
    window.resize(available.width() + 200, available.height() + 200)
    window.show()
    qtbot.wait(20)

    assert window.width() <= available.width()
    assert window.height() <= available.height()


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
