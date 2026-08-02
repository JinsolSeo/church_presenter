from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from church_presenter.domain.bible import (
    BibleBook,
    BibleChapter,
    BibleDocument,
    BibleTranslation,
    BibleVerse,
)
from church_presenter.domain.enums import ChannelRole, ContentType
from church_presenter.domain.models import AppSettings, ScreenInfo, SubtitleStyle
from church_presenter.services.bible_service import BOOK_SPECS, BibleRepository
from church_presenter.services.screen_service import MockScreenService
from church_presenter.services.settings_service import SettingsService
from church_presenter.ui import controller_window as controller_window_module
from church_presenter.ui.controller_window import ControllerWindow
from church_presenter.ui.widgets.tile_picker import TilePickerButton, TilePickerDialog

SAMPLE_SONG = Path(__file__).parents[2] / "sample_assets" / "songs" / "01_grace_morning.json"


def _repository() -> BibleRepository:
    books = tuple(
        BibleBook(
            spec.id,
            spec.name,
            order,
            (
                BibleChapter(
                    1,
                    tuple(
                        BibleVerse(number, f"{spec.name} {number}절")
                        for number in range(1, 4 if order == 1 else 2)
                    ),
                ),
                *((BibleChapter(2, (BibleVerse(1, "창세기 둘째 장 1절"),)),) if order == 1 else ()),
            ),
        )
        for order, spec in enumerate(BOOK_SPECS, start=1)
    )
    return BibleRepository(BibleDocument(BibleTranslation("test", "테스트 번역", "1"), books))


def _window(qtbot, tmp_path: Path) -> ControllerWindow:
    application = QApplication.instance()
    assert isinstance(application, QApplication)
    screens = MockScreenService([ScreenInfo("virtual", "CI Virtual", 0, 0, 1280, 720, 1.0, True)])
    window = ControllerWindow(
        application,
        screens,  # type: ignore[arg-type]
        SettingsService(tmp_path / "settings"),
        AppSettings(simulation_mode=True),
    )
    qtbot.addWidget(window)
    repository = _repository()
    window.bible_repository = repository
    window.bible_panel.set_repository(repository, tmp_path / "bible.json")
    window.show()
    return window


def test_flat_source_tabs_are_concise_and_default_to_instant(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)

    assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
        "즉석",
        "찬양",
        "성경",
        "PDF",
        "영상",
        "음악",
        "빈 화면",
    ]
    assert window.tabs.currentWidget() is window.instant_panel
    assert not hasattr(window.instant_panel, "subtabs")
    assert not hasattr(window.instant_panel, "praise_edit")
    assert not hasattr(window.instant_panel, "book_combo")


def test_praise_song_headers_follow_active_theme(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    panel = window.subtitle_panel
    assert panel.load_song_paths([SAMPLE_SONG])
    panel.add_selected_sections()
    panel.is_modified = False

    window.theme_combo.setCurrentIndex(window.theme_combo.findData("dark_modern"))

    header = panel.plan_list.item(0)
    assert header.data(Qt.ItemDataRole.UserRole) == ("entry", 0)
    assert header.foreground().color() == QColor(
        str(window.theme_manager.current_value("colors", "accent"))
    )
    assert header.font().bold()
    assert not bool(header.flags() & Qt.ItemFlag.ItemIsSelectable)


def test_bible_range_headers_follow_active_theme(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    panel = window.bible_panel
    qtbot.mouseClick(panel.add_after_button, Qt.MouseButton.LeftButton)

    window.theme_combo.setCurrentIndex(window.theme_combo.findData("dark_modern"))

    header = panel.plan_list.item(0)
    assert header.data(Qt.ItemDataRole.UserRole) == ("range", 0)
    assert header.foreground().color() == QColor(
        str(window.theme_manager.current_value("colors", "accent"))
    )
    assert header.font().bold()
    assert not bool(header.flags() & Qt.ItemFlag.ItemIsSelectable)


def test_tile_picker_uses_grids_for_books_and_numbers(qtbot) -> None:
    books = [(f"성경 {index}", index) for index in range(66)]
    book_dialog = TilePickerDialog("성경", books, 0)
    number_dialog = TilePickerDialog("장", [(str(index), index) for index in range(1, 151)], 0)
    qtbot.addWidget(book_dialog)
    qtbot.addWidget(number_dialog)

    assert book_dialog.column_count == 6
    assert number_dialog.column_count == 10
    assert len(book_dialog.findChildren(QPushButton)) == 66
    assert len(number_dialog.findChildren(QPushButton)) == 150


def test_instant_text_navigation_previews_then_requires_explicit_take(
    qtbot,
    tmp_path: Path,
) -> None:
    window = _window(qtbot, tmp_path)
    window.instant_panel.text_edit.setPlainText("차를 빼 주세요")

    qtbot.mouseClick(window.instant_panel.previous_button, Qt.MouseButton.LeftButton)

    preview = window.state.broadcast.preview_content
    assert preview.text == "차를 빼 주세요"
    assert preview.subtitle_source == "instant_text"
    assert window.state.broadcast.live_content.kind is ContentType.BLACK

    qtbot.mouseClick(window.instant_panel.take_button, Qt.MouseButton.LeftButton)

    assert window.state.broadcast.live_content == preview
    assert window.instant_panel.live_source == "instant_text"
    assert not hasattr(window.instant_panel, "preview_button")
    button_gap = (
        window.instant_panel.take_button.geometry().left()
        - window.instant_panel.next_button.geometry().right()
    )
    assert 0 < button_gap <= 12


def test_instant_navigation_group_is_centered_at_the_bottom(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    panel = window.instant_panel
    window.tabs.setCurrentWidget(panel)
    QApplication.processEvents()

    group_left = panel.previous_button.mapTo(panel, QPoint(0, 0)).x()
    group_right = panel.take_button.mapTo(panel, QPoint(0, 0)).x() + panel.take_button.width()
    group_center = (group_left + group_right) / 2

    assert abs(group_center - panel.width() / 2) <= 12
    group_top = panel.previous_button.mapTo(panel, QPoint(0, 0)).y()
    assert group_top > panel.text_edit.geometry().center().y()


def test_instant_text_editor_keeps_arrow_and_enter_keys(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    editor = window.instant_panel.text_edit
    editor.setPlainText("공지")
    editor.setFocus()
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)

    left = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
    enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)

    assert not window._handle_navigation_key(left, editor)
    assert not window._handle_navigation_key(enter, editor)
    assert window.state.broadcast.live_content.kind is ContentType.BLACK


def test_instant_text_group_size_builds_n_line_cards(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    panel = window.instant_panel
    panel.text_edit.setPlainText("첫 줄\n둘째 줄\n셋째 줄\n넷째 줄\n다섯째 줄")
    panel.set_group_size(2)

    panel.preview_current()
    assert panel.output_count == 3
    assert window.state.broadcast.preview_content.text == "첫 줄\n둘째 줄"

    panel.move_preview(1)
    assert window.state.broadcast.preview_content.text == "셋째 줄\n넷째 줄"
    panel.move_preview(1)
    assert window.state.broadcast.preview_content.text == "다섯째 줄"


def test_bible_range_builds_weekly_plan_and_navigates_preview(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    panel = window.bible_panel

    qtbot.mouseClick(panel.add_after_button, Qt.MouseButton.LeftButton)

    assert len(panel.ranges) == 1
    assert panel.output_count == 1
    assert window.state.broadcast.preview_content.subtitle_source == "bible"
    assert window.state.broadcast.preview_content.subtitle_reference == "GEN.1.1"
    assert window.state.broadcast.preview_content.text == "창세기 1절"
    assert window.state.broadcast.preview_content.subtitle_label == "창세기 1:1"
    assert (
        window.state.broadcast.preview_content.subtitle_label_style.font_size
        < window.state.broadcast.preview_content.subtitle_style.font_size
    )
    body_style = window.state.broadcast.preview_content.subtitle_style
    reference_style = SubtitleStyle(font_size=28, x_ratio=0.1, y_ratio=0.1)
    panel.set_reference_style(reference_style, "#00FF00")
    assert window.state.broadcast.preview_content.subtitle_style == body_style
    assert window.state.broadcast.preview_content.subtitle_label_style == reference_style
    qtbot.mouseClick(panel.take_button, Qt.MouseButton.LeftButton)
    assert window.state.broadcast.live_content.subtitle_source == "bible"
    assert panel.live_index == 0

    plan_path = tmp_path / "이번주_성경_콘티.json"
    assert panel.save_plan_path(plan_path)
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    assert payload["document_type"] == "church_presenter_bible_plan"
    assert payload["ranges"][0]["start"] == "GEN.1.1"
    assert "text" not in payload

    panel.ranges = []
    panel._rebuild()
    assert panel.load_plan_path(plan_path)
    assert panel.ranges[0].start.key == "GEN.1.1"
    assert panel.output_count == 1


def test_bible_panel_puts_controls_left_and_tall_cue_list_right(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    panel = window.bible_panel
    window.tabs.setCurrentWidget(panel)
    QApplication.processEvents()

    controls_position = panel.open_bible_button.mapTo(panel, QPoint(0, 0))
    list_position = panel.plan_list.mapTo(panel, QPoint(0, 0))

    assert isinstance(panel.book_combo, TilePickerButton)
    assert isinstance(panel.start_chapter_combo, TilePickerButton)
    assert isinstance(panel.start_verse_combo, TilePickerButton)
    assert controls_position.x() < list_position.x()
    assert panel.plan_list.height() > panel.open_bible_button.height() * 3
    assert panel.open_plan_button.text() == "콘티 열기"
    assert panel.save_plan_button.text() == "콘티 저장"
    assert panel.add_before_button.property("variant") == "primary"
    assert panel.add_after_button.property("variant") == "primary"
    assert panel.style_button.y() < panel.book_combo.y()
    selector_centers = {
        widget.geometry().center().y()
        for widget in (
            panel.book_combo,
            panel.start_chapter_combo,
            panel.start_verse_combo,
            panel.end_chapter_combo,
            panel.end_verse_combo,
        )
    }
    assert len(selector_centers) == 1
    assert [action.text() for action in panel.style_button.menu().actions()] == [
        "본문 스타일",
        "구절 정보 스타일",
    ]


def test_bible_range_end_follows_a_later_start_verse(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    panel = window.bible_panel

    panel.start_verse_combo.setCurrentIndex(2)

    assert panel.start_verse_combo.currentData() == 3
    assert panel.end_verse_combo.currentData() == 3


def test_bible_ranges_insert_before_and_after_the_selected_cue(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    panel = window.bible_panel
    panel.end_verse_combo.setCurrentIndex(2)
    panel.add_selected_range()
    panel.navigate(1)

    panel.book_combo.setCurrentIndex(1)
    qtbot.mouseClick(panel.add_before_button, Qt.MouseButton.LeftButton)

    assert [(row.start.key, row.end.key) for row in panel.ranges] == [
        ("GEN.1.1", "GEN.1.1"),
        ("EXO.1.1", "EXO.1.1"),
        ("GEN.1.2", "GEN.1.3"),
    ]
    assert panel._content_at(panel.preview_index).subtitle_reference == "EXO.1.1"

    panel.book_combo.setCurrentIndex(2)
    qtbot.mouseClick(panel.add_after_button, Qt.MouseButton.LeftButton)

    assert [(row.start.key, row.end.key) for row in panel.ranges] == [
        ("GEN.1.1", "GEN.1.1"),
        ("EXO.1.1", "EXO.1.1"),
        ("LEV.1.1", "LEV.1.1"),
        ("GEN.1.2", "GEN.1.3"),
    ]
    assert panel._content_at(panel.preview_index).subtitle_reference == "LEV.1.1"


def test_bible_group_size_builds_reference_ranges_without_crossing_chapters(
    qtbot,
    tmp_path: Path,
) -> None:
    window = _window(qtbot, tmp_path)
    panel = window.bible_panel
    panel.set_group_size(2)
    panel.end_chapter_combo.setCurrentIndex(1)
    panel.end_verse_combo.setCurrentIndex(0)

    panel.add_selected_range()

    assert panel.output_count == 3
    first = panel._content_at(0)
    second = panel._content_at(1)
    third = panel._content_at(2)
    assert first.subtitle_label == "창세기 1:1-2"
    assert first.text == "창세기 1절\n창세기 2절"
    assert second.subtitle_label == "창세기 1:3"
    assert third.subtitle_label == "창세기 2:1"


def test_bible_grouping_does_not_join_separate_ranges(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    panel = window.bible_panel
    panel.set_group_size(2)
    panel.add_selected_range()
    panel.start_verse_combo.setCurrentIndex(1)
    panel.end_verse_combo.setCurrentIndex(1)
    panel.add_selected_range()

    assert panel.output_count == 2
    assert panel._content_at(0).subtitle_label == "창세기 1:1"
    assert panel._content_at(1).subtitle_label == "창세기 1:2"


def test_bible_body_style_dialog_applies_verse_group_size(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    window = _window(qtbot, tmp_path)
    panel = window.bible_panel
    panel.end_verse_combo.setCurrentIndex(2)
    panel.add_selected_range()
    assert panel.output_count == 3

    class AcceptedStyleDialog:
        def __init__(self, *_args, **_kwargs) -> None:
            self.result_style = SubtitleStyle(font_size=61)
            self.result_key_color = "#00FF00"
            self.result_preset = "Lower Third"
            self.result_group_size = 2

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        controller_window_module,
        "SubtitleStyleDialog",
        AcceptedStyleDialog,
    )
    window.tabs.setCurrentWidget(panel)

    window.open_source_style_settings("bible")

    assert panel.group_size == 2
    assert panel.output_count == 2
    assert window.settings.bible_group_size == 2
    assert (
        window.state.broadcast.preview_content.subtitle_label
        == "창세기 1:1-2"
    )


def test_instant_text_style_dialog_applies_and_persists_group_size(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    window = _window(qtbot, tmp_path)
    panel = window.instant_panel
    panel.text_edit.setPlainText("첫 줄\n둘째 줄\n셋째 줄")
    panel.preview_current()

    class AcceptedStyleDialog:
        def __init__(self, *_args, **_kwargs) -> None:
            self.result_style = SubtitleStyle(font_size=67)
            self.result_key_color = "#123456"
            self.result_preset = "Lower Third"
            self.result_group_size = 2

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(controller_window_module, "SubtitleStyleDialog", AcceptedStyleDialog)
    window.tabs.setCurrentWidget(panel)

    window.open_source_style_settings("instant_text")

    assert panel.group_size == 2
    assert panel.output_count == 2
    assert panel.text_style.font_size == 67
    assert panel.text_key == "#123456"
    assert window.settings.instant_text_group_size == 2
    assert window.state.broadcast.preview_content.text == "첫 줄\n둘째 줄"


def test_only_prepared_praise_and_bible_can_be_saved_to_worship_order(
    qtbot,
    tmp_path: Path,
) -> None:
    window = _window(qtbot, tmp_path)
    window.instant_panel.text_edit.setPlainText("즉석 공지")
    window.instant_panel.preview_current()

    assert not window.save_preview_preset("즉석")
    assert not window.preview_presets

    window.bible_panel.add_selected_range()
    assert window.save_preview_preset("성경 봉독")
    cue = window.preview_presets[0].broadcast_content
    assert cue.subtitle_source == "bible"
    assert cue.subtitle_reference == "GEN.1.1"
    assert window.state.broadcast.live_content.kind is ContentType.BLACK

    window.take(ChannelRole.BROADCAST)
    assert window.state.broadcast.live_content.subtitle_reference == "GEN.1.1"


def test_prepared_praise_uses_semantic_song_reference(
    qtbot,
    tmp_path: Path,
) -> None:
    window = _window(qtbot, tmp_path)
    assert window.subtitle_panel.load_song_paths([SAMPLE_SONG])
    window.subtitle_panel.add_selected_sections()
    window.subtitle_panel.navigate(0)

    assert window.save_preview_preset("찬양")
    cue = window.preview_presets[0].broadcast_content
    assert cue.subtitle_source == "praise"
    assert cue.subtitle_reference.startswith("song:")

    window.subtitle_panel.is_modified = False


def test_praise_plan_round_trip_restores_song_and_selected_sections(
    qtbot,
    tmp_path: Path,
) -> None:
    window = _window(qtbot, tmp_path)
    panel = window.subtitle_panel
    panel.set_group_size(2)
    assert panel.load_song_paths([SAMPLE_SONG])
    panel.add_selected_sections()
    reference = panel._content_at(0).subtitle_reference
    plan_path = tmp_path / "이번주_찬양_콘티.json"
    panel.plan_path = plan_path
    assert panel.save_plan()

    restored_window = _window(qtbot, tmp_path / "restored")
    restored = restored_window.subtitle_panel
    assert restored.load_plan_path(plan_path, warn=False)

    assert restored.entries[0].sequence == ("chorus",)
    assert restored.output_count == 2
    assert restored.content_for_reference(reference).text == (
        "은혜로 걷네 은혜로 살리\n모든 순간 주를 의지해"
    )


def test_returning_from_instant_restores_prepared_preview_but_keeps_live(
    qtbot,
    tmp_path: Path,
) -> None:
    window = _window(qtbot, tmp_path)
    assert window.subtitle_panel.load_song_paths([SAMPLE_SONG])
    window.subtitle_panel.add_selected_sections()
    window.tabs.setCurrentWidget(window.subtitle_panel)
    window.subtitle_panel.restore_preview()

    window.tabs.setCurrentWidget(window.instant_panel)
    window.instant_panel.text_edit.setPlainText("즉석 공지")
    window.instant_panel.preview_current()
    window.take(ChannelRole.BROADCAST)
    instant_live = window.state.broadcast.live_content

    window.tabs.setCurrentWidget(window.subtitle_panel)

    assert window.state.broadcast.preview_content.text.startswith("은혜로 걷네")
    assert window.state.broadcast.preview_content.subtitle_source == "praise"
    assert window.state.broadcast.live_content == instant_live
    window.subtitle_panel.is_modified = False
