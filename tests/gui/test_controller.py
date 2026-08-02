from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton

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
from church_presenter.ui.controller_window import (
    CONTROLLER_DEFAULT_SIZE,
    CONTROLLER_DESIGN_SIZE,
    CONTROLLER_MINIMUM_SIZE,
    ControllerWindow,
)
from church_presenter.ui.styles import apply_application_style

SAMPLE_SONGS = Path(__file__).parents[2] / "sample_assets" / "songs"


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


def prepare_sample_praise(
    window: ControllerWindow,
    *,
    group_size: int = 1,
    section_ids: tuple[str, ...] = ("verse_1",),
) -> None:
    panel = window.subtitle_panel
    panel.set_group_size(group_size)
    assert panel.load_song_paths([SAMPLE_SONGS / "01_grace_morning.json"])
    for row in range(panel.section_list.count()):
        item = panel.section_list.item(row)
        item.setCheckState(
            Qt.CheckState.Checked
            if item.data(Qt.ItemDataRole.UserRole) in section_ids
            else Qt.CheckState.Unchecked
        )
    panel.add_selected_sections()
    panel.is_modified = False


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


def test_theme_switch_is_persisted_without_changing_preview_or_live(
    qtbot,
    tmp_path: Path,
) -> None:
    window = make_controller(qtbot, tmp_path)
    preview = Content.subtitle("Theme-safe Preview", 0, SubtitleStyle(), "#00FF00")
    window.set_preview(ChannelRole.BROADCAST, preview)
    live_before = window.state.broadcast.live_content

    window.theme_combo.setCurrentIndex(window.theme_combo.findData("dark_modern"))

    assert window.settings.current_theme == "dark_modern"
    assert window.theme_manager.current_theme_id() == "dark_modern"
    assert window.settings_service.load().settings.current_theme == "dark_modern"
    assert window.state.broadcast.preview_content == preview
    assert window.state.broadcast.live_content == live_before


@pytest.mark.parametrize(
    "theme_id",
    [
        "light_professional",
        "dark_modern",
        "minimalist_light",
        "warm_linen",
        "deep_ocean",
        "graphite_violet",
    ],
)
def test_all_themes_subtitle_cards_use_only_live_and_preview_highlights(
    qtbot,
    tmp_path: Path,
    theme_id: str,
) -> None:
    window = make_controller(qtbot, tmp_path)
    window.theme_combo.setCurrentIndex(window.theme_combo.findData(theme_id))
    panel = window.subtitle_panel
    prepare_sample_praise(window, section_ids=("verse_1", "chorus"))
    panel.live_index = 0
    panel.preview_index = 2
    panel._refresh_labels()
    cue_items = [
        panel.card_list.item(row)
        for row in range(panel.card_list.count())
        if panel.card_list.item(row).data(Qt.ItemDataRole.UserRole)[0] == "cue"
    ]
    live, previous, preview, next_item, normal = cue_items[:5]

    assert panel.card_list.objectName() == "SubtitleCardList"
    assert live.background().color() == QColor(
        str(window.theme_manager.current_value("colors", "live"))
    )
    assert preview.background().color() == QColor(
        str(window.theme_manager.current_value("colors", "accent"))
    )
    assert previous.background().color().alpha() == 0
    assert next_item.background().color().alpha() == 0
    expected_text = QColor(str(window.theme_manager.current_value("colors", "text_primary")))
    assert previous.foreground().color() == expected_text
    assert preview.foreground().color() == QColor(
        str(window.theme_manager.current_value("colors", "text_on_accent"))
    )
    assert next_item.foreground().color() == expected_text
    assert normal.foreground().color() == expected_text
    assert live.text().startswith("[LIVE]  ")
    assert preview.text().startswith("[PREVIEW]  ")
    assert not previous.text().startswith("[")
    assert not next_item.text().startswith("[")
    assert not normal.text().startswith("[")

    panel.live_index = panel.preview_index
    panel._refresh_labels()
    combined = cue_items[panel.preview_index]
    assert combined.text().startswith("[LIVE + PREVIEW]  ")
    assert panel.card_list.property("selectedCardLive") is True
    assert combined.background().color() == QColor(
        str(window.theme_manager.current_value("colors", "live"))
    )


def test_monitor_semantics_and_take_variants_are_explicit(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)

    assert window.broadcast_preview.state_label.text() == "PREVIEW"
    assert window.broadcast_live.state_label.text() == "LIVE"
    assert window.broadcast_preview.title.text() == "송출"
    assert window.venue_preview.title.text() == "현장"
    assert window.broadcast_preview.property("stateRole") == "preview"
    assert window.broadcast_live.property("stateRole") == "live"
    assert window.sync_take_button.property("variant") == "take"
    assert window.pdf_panel.take_button.property("variant") == "take"
    assert window.pdf_panel.take_both_button.property("variant") == "take"
    assert window.video_panel.cue_button.property("variant") == "secondary"
    assert window.video_panel.cue_both_button.property("variant") == "primary"
    assert window.video_panel.take_button.property("variant") == "secondary"
    assert window.video_panel.take_both_button.property("variant") == "take"
    assert window.video_panel.target_combo.itemText(0) == "송출"
    assert window.video_panel.target_combo.itemText(1) == "현장"


def test_controller_layout_declares_fhd_baseline_and_responsive_minimum(
    qtbot,
    tmp_path: Path,
) -> None:
    window = make_controller(qtbot, tmp_path)

    assert CONTROLLER_DESIGN_SIZE.width() == 1920
    assert CONTROLLER_DESIGN_SIZE.height() == 1080
    assert CONTROLLER_DEFAULT_SIZE.width() == 1600
    assert CONTROLLER_DEFAULT_SIZE.height() == 900
    assert window.minimumSize() == CONTROLLER_MINIMUM_SIZE
    assert window.root_scroll.widgetResizable()
    assert window.app_title.text() == "Church Presenter"
    assert "Phase 2" not in window.app_title.text()
    assert window.byline.text() == "by Jinsol"
    assert window.title_row.indexOf(window.app_title) == 0
    assert window.title_row.indexOf(window.byline) == 1


def test_named_preview_preset_applies_without_changing_live(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    prepare_sample_praise(window)
    broadcast = window.subtitle_panel._content_at(0)
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
        lambda: (
            window.state.broadcast.is_ready and window.state.broadcast.preview_content.pdf_page == 2
        ),
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
    assert window.preview_preset_panel.file_label.text() == order_path.name
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
    prepare_sample_praise(window)
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

    assert window.state.broadcast.preview_content.text == "주님의 은혜를 노래해"
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
    assert window.subtitle_panel.song_combo.width() > 0


def test_controller_gives_more_extra_height_to_monitors(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    window.setFixedSize(1280, 720)
    qtbot.wait(20)

    upper, lower = window.workspace_splitter.sizes()
    assert upper > lower
    assert window.broadcast_preview.surface.height() >= 100


@pytest.mark.parametrize(
    ("width", "height", "density", "minimum_surface_height"),
    [
        (1920, 1080, "normal", 160),
        (1600, 900, "compact", 145),
        (1366, 768, "compact", 110),
        (1280, 720, "compact", 95),
        (800, 600, "compact", 36),
    ],
)
def test_controller_preserves_monitoring_area_across_resolutions(
    qtbot,
    tmp_path: Path,
    width: int,
    height: int,
    density: str,
    minimum_surface_height: int,
) -> None:
    window = make_controller(qtbot, tmp_path)
    window.tabs.setCurrentWidget(window.video_panel)
    window.setFixedSize(width, height)
    qtbot.wait(30)

    assert window.property("uiDensity") == density
    assert window.root_scroll.verticalScrollBar().maximum() == 0
    assert window.root_scroll.horizontalScrollBar().maximum() == 0
    assert window.content_scroll.verticalScrollBar().maximum() == 0
    assert window.broadcast_preview.surface.height() >= minimum_surface_height
    assert window.venue_live.surface.height() >= minimum_surface_height
    assert window.workspace_splitter.sizes()[0] > window.workspace_splitter.sizes()[1]
    assert window.preview_preset_dock.isVisible()
    assert not window.preview_preset_dock.isFloating()
    if density == "compact":
        assert window.sync_take_button.height() <= 40
        assert not window.video_panel.info_label.isVisible()
    else:
        assert window.sync_take_button.height() >= 44


def test_lower_workspace_has_no_outer_scrollbar_on_laptop(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    window.setFixedSize(1280, 720)

    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        qtbot.wait(10)
        assert window.content_scroll.verticalScrollBar().maximum() == 0


def test_worship_order_dock_is_not_hidden_or_floated_on_resize(
    qtbot,
    tmp_path: Path,
) -> None:
    window = make_controller(qtbot, tmp_path)
    window.setFixedSize(1000, 720)
    qtbot.wait(20)

    assert window.preview_preset_dock.isVisible()
    assert not window.preview_preset_dock.isFloating()
    assert not bool(
        window.preview_preset_dock.features()
        & window.preview_preset_dock.DockWidgetFeature.DockWidgetClosable
    )

    window.preview_preset_dock.close()
    qtbot.wait(10)

    assert window.preview_preset_dock.isVisible()
    assert not window.preview_preset_dock.isFloating()

    window.preview_preset_dock.hide()
    window._restore_panel_layout()
    qtbot.wait(10)
    assert window.preview_preset_dock.isVisible()


def test_header_replaces_worship_order_button_with_remote_connection(
    qtbot,
    tmp_path: Path,
) -> None:
    window = make_controller(qtbot, tmp_path)
    header_texts = {
        button.text() for button in window.header_actions_widget.findChildren(QPushButton)
    }

    assert "예배 순서" not in header_texts
    assert window.remote_connection_button.text() == "원격 연결"
    assert window.remote_connection_button.property("variant") == "secondary"
    assert not hasattr(window, "preview_presets_button")


def test_workspace_splitter_state_is_restored(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    window.setFixedSize(1280, 720)
    window.workspace_splitter.setSizes([430, 180])
    qtbot.wait(20)
    window._persist_settings()
    saved_state = window.settings.workspace_splitter_state
    window.hide()

    application = QApplication.instance()
    assert isinstance(application, QApplication)
    screens = MockScreenService([ScreenInfo("virtual", "CI Virtual", 0, 0, 1280, 720, 1.0, True)])
    service = SettingsService(tmp_path / "settings")
    restored = ControllerWindow(
        application,
        screens,  # type: ignore[arg-type]
        service,
        service.load().settings,
    )
    qtbot.addWidget(restored)
    restored.setFixedSize(1280, 720)
    restored.show()
    qtbot.wait(30)

    assert saved_state
    assert restored._workspace_splitter_state_restored is True
    assert restored.workspace_splitter.sizes()[0] > restored.workspace_splitter.sizes()[1]


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
    assert "송출 TAKE 완료" in window.status.text()
    window.pdf_panel.set_target_role(ChannelRole.VENUE)
    qtbot.mouseClick(window.pdf_panel.take_button, Qt.MouseButton.LeftButton)
    assert "현장 TAKE 완료" in window.status.text()


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


def test_praise_keyboard_navigation_uses_the_read_only_card_list(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    panel = window.subtitle_panel
    window.tabs.setCurrentWidget(panel)
    prepare_sample_praise(window)
    panel.navigate(0)
    panel.card_list.setFocus()
    qtbot.keyClick(panel.card_list, Qt.Key.Key_Right)

    assert panel.preview_index == 1
    assert not hasattr(panel, "line_edit")
    assert not hasattr(panel, "line_list")


def test_praise_single_add_button_supports_chorus_and_full_configurations(
    qtbot,
    tmp_path: Path,
) -> None:
    window = make_controller(qtbot, tmp_path)
    panel = window.subtitle_panel
    panel.set_group_size(2)
    assert panel.load_song_paths([SAMPLE_SONGS / "01_grace_morning.json"])
    panel.add_selected_sections()
    for row in range(panel.section_list.count()):
        panel.section_list.item(row).setCheckState(Qt.CheckState.Checked)
    panel.add_selected_sections()

    assert len(panel.entries) == 2
    assert panel.entries[0].sequence == ("chorus",)
    assert panel.entries[1].sequence.count("chorus") == 3
    assert panel.output_count == 13
    assert panel.is_modified
    panel.is_modified = False


def test_praise_panel_keeps_controls_left_and_cards_wide_without_elision(
    qtbot,
    tmp_path: Path,
) -> None:
    window = make_controller(qtbot, tmp_path)
    panel = window.subtitle_panel
    window.tabs.setCurrentWidget(panel)
    prepare_sample_praise(window)

    controls_position = panel.open_song_button.mapTo(panel, QPoint(0, 0))
    cards_position = panel.card_list.mapTo(panel, QPoint(0, 0))
    assert controls_position.x() < cards_position.x()
    assert cards_position.x() >= 350
    assert panel.card_list.width() > panel.open_song_button.width() * 2
    assert panel.card_list.wordWrap()
    assert panel.card_list.textElideMode() is Qt.TextElideMode.ElideNone
    last_section = panel.section_list.item(panel.section_list.count() - 1)
    assert (
        panel.section_list.visualItemRect(last_section).bottom()
        <= panel.section_list.viewport().height()
    )
    section_position = panel.section_list.mapTo(panel, QPoint(0, 0))
    add_position = panel.add_button.mapTo(panel, QPoint(0, 0))
    assert section_position.x() + panel.section_list.width() <= add_position.x()
    assert panel.add_button.y() < panel.remove_button.y() < panel.move_up_button.y()
    assert panel.move_up_button.y() == panel.move_down_button.y()
    assert (
        panel.style_button.geometry().center().y()
        == panel.open_song_button.geometry().center().y()
    )
    assert (
        panel.create_song_button.geometry().center().y()
        == panel.open_song_button.geometry().center().y()
    )
    assert (
        panel.previous_button.geometry().center().y()
        == panel.take_button.geometry().center().y()
    )
    assert "은혜의 아침" in panel.card_list.item(0).text()
    assert panel.open_song_button.text() == "곡 JSON"
    assert panel.open_plan_button.text() == "콘티 열기"
    assert panel.save_plan_button.text() == "콘티 저장"
    assert panel.create_song_button.text() == "곡 만들기"
    assert panel.add_button.text() == "추가"
    assert panel.style_button.text() == "Style"


def test_blank_screen_presets_prepare_preview_before_take(
    qtbot,
    tmp_path: Path,
) -> None:
    window = make_controller(qtbot, tmp_path)
    panel = window.black_panel
    tab_index = window.tabs.indexOf(window.misc_panel)

    assert window.tabs.tabText(tab_index) == "기타"
    assert panel.preset_panel.maximumWidth() == 240
    qtbot.mouseClick(panel.preset_buttons["#00FF00"], Qt.MouseButton.LeftButton)
    assert window.state.broadcast.preview_content.kind is ContentType.BLACK
    assert window.state.broadcast.live_content.kind is ContentType.BLACK

    qtbot.mouseClick(panel.preview_broadcast_button, Qt.MouseButton.LeftButton)
    preview = window.state.broadcast.preview_content
    assert preview.kind is ContentType.SOLID_COLOR
    assert preview.background_color == "#00FF00"
    assert window.state.broadcast.live_content.kind is ContentType.BLACK

    qtbot.mouseClick(panel.take_broadcast_button, Qt.MouseButton.LeftButton)
    assert window.state.broadcast.live_content == preview
    assert window.broadcast_simulator is not None
    assert window.broadcast_simulator.surface.target_content == preview

    qtbot.mouseClick(panel.preset_buttons["#0000FF"], Qt.MouseButton.LeftButton)
    qtbot.mouseClick(panel.send_both_button, Qt.MouseButton.LeftButton)
    assert window.state.broadcast.preview_content == Content.solid_color("#0000FF")
    assert window.state.venue.preview_content == Content.solid_color("#0000FF")
    assert window.state.broadcast.live_content == preview


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
    prepare_sample_praise(window)
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
    assert window.state.broadcast.live_content.kind is ContentType.BLACK
    assert window.state.venue.live_content.kind is ContentType.BLACK
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
    prepare_sample_praise(window)
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


def test_sync_checkbox_uses_one_indicator_and_compact_label(qtbot, tmp_path: Path) -> None:
    window = make_controller(qtbot, tmp_path)
    assert window.sync_content_check.objectName() == "SyncContentCheck"
    assert window.sync_auto_take_check.objectName() == "LinkedAutoTakeCheck"
    assert not hasattr(window, "sync_hint")
    assert window.sync_content_check.text() == "동시 진행"
    assert window.sync_auto_take_check.text() == "바로 Live"
    assert "☐" not in window.sync_content_check.text()
    assert window.sync_take_button.text() == "TAKE BOTH"
    checkbox_gap = (
        window.sync_auto_take_check.geometry().left()
        - window.sync_content_check.geometry().right()
        - 1
    )
    assert checkbox_gap >= 16
    window.sync_content_check.setChecked(True)
    assert window.sync_content_check.text() == "동시 진행"


def test_broadcast_chroma_override_only_replaces_broadcast_displays(
    qtbot,
    tmp_path: Path,
) -> None:
    window = make_controller(qtbot, tmp_path)
    broadcast_live = Content.subtitle("현재 송출", 0, SubtitleStyle(), "#00FF00")
    venue_live = Content.solid_color("#0000FF")
    broadcast_preview = Content.subtitle("다음 송출", 1, SubtitleStyle(), "#00FF00")
    venue_preview = Content.black()
    window.state.broadcast.live_content = broadcast_live
    window.state.venue.live_content = venue_live
    window.state.set_preview(ChannelRole.BROADCAST, broadcast_preview)
    window.state.set_preview(ChannelRole.VENUE, venue_preview)
    window._refresh_all()

    assert window.sync_chroma_check.text() == "크로마키"
    assert window.sync_chroma_check.objectName() == "BroadcastChromaCheck"
    assert "가장 최근" in window.sync_chroma_check.toolTip()
    assert not window.sync_chroma_check.isChecked()
    qtbot.mouseClick(window.sync_chroma_check, Qt.MouseButton.LeftButton)

    green = Content.solid_color("#00FF00")
    assert window.state.broadcast.live_content == broadcast_live
    assert window.state.venue.live_content == venue_live
    assert window.state.broadcast.preview_content == broadcast_preview
    assert window.state.venue.preview_content == venue_preview
    assert window.broadcast_live.surface.target_content == green
    assert window.venue_live.surface.target_content == venue_live

    assert window.start_outputs()
    assert window.broadcast_simulator is not None
    assert window.venue_simulator is not None
    assert window.broadcast_simulator.surface.target_content == green
    assert window.venue_simulator.surface.target_content == venue_live


def test_broadcast_chroma_override_reveals_latest_take_when_cleared(
    qtbot,
    tmp_path: Path,
) -> None:
    window = make_controller(qtbot, tmp_path)
    first = Content.subtitle("첫 화면", 0, SubtitleStyle(), "#00FF00")
    latest = Content.subtitle("새 화면", 1, SubtitleStyle(), "#00FF00")
    window.set_preview(ChannelRole.BROADCAST, first)
    assert window.take(ChannelRole.BROADCAST)
    window.sync_chroma_check.setChecked(True)

    window.set_preview(ChannelRole.BROADCAST, latest)
    assert window.take(ChannelRole.BROADCAST)

    green = Content.solid_color("#00FF00")
    assert window.state.broadcast.live_content == latest
    assert window.broadcast_live.surface.target_content == green
    assert window.broadcast_simulator is not None
    assert window.broadcast_simulator.surface.target_content == green

    window.sync_chroma_check.setChecked(False)

    assert window.broadcast_live.surface.target_content == latest
    assert window.broadcast_simulator.surface.target_content == latest
    assert "최신 송출 Live" in window.status.text()


def test_take_both_keeps_only_broadcast_visually_overridden(
    qtbot,
    tmp_path: Path,
) -> None:
    window = make_controller(qtbot, tmp_path)
    broadcast = Content.subtitle("찬양", 0, SubtitleStyle(), "#00FF00")
    venue = Content.solid_color("#0000FF")
    window.set_preview(ChannelRole.BROADCAST, broadcast)
    window.set_preview(ChannelRole.VENUE, venue)
    window.sync_content_check.setChecked(True)
    window.sync_auto_take_check.setChecked(True)
    window.sync_chroma_check.setChecked(True)

    assert window.take_both()

    green = Content.solid_color("#00FF00")
    assert window.sync_content_check.isChecked()
    assert window.sync_auto_take_check.isChecked()
    assert window.state.broadcast.live_content == broadcast
    assert window.state.venue.live_content == venue
    assert window.broadcast_live.surface.target_content == green
    assert window.venue_live.surface.target_content == venue
    assert window.broadcast_simulator is not None
    assert window.venue_simulator is not None
    assert window.broadcast_simulator.surface.target_content == green
    assert window.venue_simulator.surface.target_content == venue


@pytest.mark.parametrize("width,height", [(1920, 1080), (1366, 768)])
def test_pdf_action_buttons_match_page_move_metrics(
    qtbot,
    tmp_path: Path,
    width: int,
    height: int,
) -> None:
    window = make_controller(qtbot, tmp_path)
    window.resize(width, height)
    qtbot.wait(20)
    panel = window.pdf_panel
    buttons = (
        panel.go_button,
        panel.send_both_button,
        panel.take_button,
        panel.take_both_button,
    )

    assert all(button.property("pdfAction") is True for button in buttons)
    assert len({button.height() for button in buttons}) == 1
    assert len({button.fontMetrics().height() for button in buttons}) == 1
    assert panel.send_both_button.property("variant") == "primary"
    assert panel.take_button.property("variant") == "take"
    assert panel.take_both_button.property("variant") == "take"


def test_linked_auto_take_moves_live_with_page_and_arrow_keys(
    qtbot,
    tmp_path: Path,
) -> None:
    path = tmp_path / "auto-live.pdf"
    create_pdf(path)
    window = make_controller(qtbot, tmp_path)
    panel = window.subtitle_panel
    prepare_sample_praise(window)
    panel.navigate(0)
    qtbot.waitUntil(lambda: window.pdf_panel.file_list.count() == 1, timeout=5000)
    window.pdf_panel.set_target_role(ChannelRole.VENUE)
    window.pdf_panel.file_list.setCurrentRow(0)
    qtbot.waitUntil(lambda: window.pdf_panel.page_count == 3, timeout=5000)
    qtbot.waitUntil(lambda: window.state.venue.is_ready, timeout=10000)
    assert window.take_both()
    assert window.state.broadcast.live_content.subtitle_card_index == 0
    assert window.state.venue.live_content.pdf_page == 0

    window.sync_content_check.setChecked(True)
    window.sync_auto_take_check.setChecked(True)
    window.sync_next_button.setFocus()
    qtbot.keyClick(window.sync_next_button, Qt.Key.Key_PageDown)

    assert panel.preview_index == 1
    assert window.pdf_panel.preview_page == 1
    qtbot.waitUntil(
        lambda: (
            window.state.broadcast.live_content.subtitle_card_index == 1
            and window.state.venue.live_content.pdf_page == 1
        ),
        timeout=10000,
    )

    qtbot.keyClick(window.sync_next_button, Qt.Key.Key_Up)
    qtbot.waitUntil(
        lambda: (
            window.state.broadcast.live_content.subtitle_card_index == 0
            and window.state.venue.live_content.pdf_page == 0
        ),
        timeout=10000,
    )


def test_linked_auto_take_render_failure_preserves_live(
    qtbot,
    tmp_path: Path,
) -> None:
    path = tmp_path / "failed.pdf"
    path.write_bytes(b"pdf marker")
    window = make_controller(qtbot, tmp_path)
    window.sync_content_check.setChecked(True)
    window.sync_auto_take_check.setChecked(True)
    window.state.set_preview(
        ChannelRole.BROADCAST,
        Content.subtitle("다음", 0, SubtitleStyle(), "#00FF00"),
    )
    window.state.set_preview(ChannelRole.VENUE, Content.pdf(path, 0), ready=False)
    before = (
        window.state.broadcast.live_content,
        window.state.venue.live_content,
    )

    window._queue_linked_auto_take()
    assert window._linked_auto_take_pending
    window.mark_preview_ready(ChannelRole.VENUE, False, "렌더 실패")

    assert not window._linked_auto_take_pending
    assert (
        window.state.broadcast.live_content,
        window.state.venue.live_content,
    ) == before
    assert "바로 Live 취소" in window.status.text()
