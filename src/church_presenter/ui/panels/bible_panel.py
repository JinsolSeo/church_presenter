from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from church_presenter.domain.bible import BiblePassageRange, BibleReference, BibleVerse
from church_presenter.domain.models import Content, SubtitleStyle
from church_presenter.services.bible_service import BibleRepository
from church_presenter.services.json_io import atomic_write_json, read_json_object
from church_presenter.ui.widgets.tile_picker import TilePickerButton


class BiblePanel(QWidget):
    """Prepare an ordered weekly Bible citation plan from semantic ranges."""

    preview_requested = Signal(object)
    take_requested = Signal()
    style_requested = Signal()
    reference_style_requested = Signal()
    status_changed = Signal(str)
    bible_file_changed = Signal(str)
    plan_file_changed = Signal(str)

    def __init__(
        self,
        style: SubtitleStyle,
        reference_style: SubtitleStyle,
        key_color: str,
        group_size: int = 1,
        repository: BibleRepository | None = None,
        bible_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.subtitle_style = style
        self.reference_style = reference_style
        self.key_color = key_color
        self.group_size = max(1, group_size)
        self.repository = repository
        self.bible_path = bible_path
        self.plan_path: Path | None = None
        self.ranges: list[BiblePassageRange] = []
        self._flat: list[tuple[tuple[BibleReference, BibleVerse], ...]] = []
        self.preview_index = -1
        self.live_index = -1
        self._group_header_color = QColor(Qt.GlobalColor.black)

        layout = QHBoxLayout(self)
        controls_host = QWidget()
        controls_host.setMinimumWidth(280)
        controls_host.setMaximumWidth(380)
        controls = QVBoxLayout(controls_host)
        controls.setSpacing(10)

        source_row = QHBoxLayout()
        self.source_label = QLabel(bible_path.name if bible_path else "성경 JSON을 선택하세요")
        self.source_label.setToolTip(str(bible_path) if bible_path else "")
        self.source_label.setProperty("role", "secondary")
        self.open_bible_button = QPushButton("성경 JSON")
        self.open_plan_button = QPushButton("콘티 열기")
        self.save_plan_button = QPushButton("콘티 저장")
        self.open_bible_button.setToolTip(
            f"성경 본문 JSON\n{bible_path}" if bible_path else "성경 본문 JSON을 선택합니다."
        )
        self.open_plan_button.setToolTip("저장해 둔 이번 주 성경 범위 콘티를 불러옵니다.")
        self.save_plan_button.setToolTip(
            "현재 범위 목록만 저장합니다. 성경 본문은 저장하지 않습니다."
        )
        self.style_button = QPushButton("Style")
        style_menu = QMenu(self.style_button)
        body_style_action = style_menu.addAction("본문 스타일")
        reference_style_action = style_menu.addAction("구절 정보 스타일")
        self.style_button.setMenu(style_menu)
        source_row.addWidget(self.open_bible_button)
        self.plan_label = QLabel("새 콘티")
        self.plan_label.setProperty("role", "secondary")
        source_row.addWidget(self.open_plan_button)
        source_row.addWidget(self.save_plan_button)
        source_row.addWidget(self.style_button)
        controls.addLayout(source_row)
        self.source_label.hide()
        self.plan_label.hide()

        range_row = QHBoxLayout()
        range_row.setContentsMargins(0, 7, 0, 7)
        range_row.setSpacing(4)
        self.book_combo = TilePickerButton("성경")
        self.start_chapter_combo = TilePickerButton("시작 장")
        self.start_verse_combo = TilePickerButton("시작 절")
        self.end_chapter_combo = TilePickerButton("끝 장")
        self.end_verse_combo = TilePickerButton("끝 절")
        self.add_before_button = QPushButton("앞에 추가")
        self.add_after_button = QPushButton("뒤에 추가")
        self.add_before_button.setProperty("variant", "primary")
        self.add_after_button.setProperty("variant", "primary")
        self.add_before_button.setToolTip("오른쪽에서 선택한 구절 바로 앞에 범위 추가")
        self.add_after_button.setToolTip("오른쪽에서 선택한 구절 바로 뒤에 범위 추가")
        self.book_combo.setMinimumWidth(90)
        for combo in (
            self.start_chapter_combo,
            self.start_verse_combo,
            self.end_chapter_combo,
            self.end_verse_combo,
        ):
            combo.setMinimumWidth(40)
        range_row.addWidget(QLabel("성경"))
        range_row.addWidget(self.book_combo, 2)
        range_row.addWidget(QLabel("시작"))
        range_row.addWidget(self.start_chapter_combo)
        range_row.addWidget(QLabel(":"))
        range_row.addWidget(self.start_verse_combo)
        range_row.addWidget(QLabel("끝"))
        range_row.addWidget(self.end_chapter_combo)
        range_row.addWidget(QLabel(":"))
        range_row.addWidget(self.end_verse_combo)
        controls.addLayout(range_row)

        edit_row = QHBoxLayout()
        self.remove_button = QPushButton("삭제")
        self.move_up_button = QPushButton("▲")
        self.move_down_button = QPushButton("▼")
        self.remove_button.setToolTip("선택한 범위 삭제")
        self.move_up_button.setToolTip("선택한 범위를 위로")
        self.move_down_button.setToolTip("선택한 범위를 아래로")
        edit_row.addWidget(self.add_before_button)
        edit_row.addWidget(self.add_after_button)
        edit_row.addWidget(self.remove_button)
        edit_row.addWidget(self.move_up_button)
        edit_row.addWidget(self.move_down_button)
        controls.addLayout(edit_row)

        navigation_row = QHBoxLayout()
        self.previous_button = QPushButton("◀ 이전")
        self.next_button = QPushButton("다음 ▶")
        self.take_button = QPushButton("송출")
        self.take_button.setProperty("variant", "take")
        navigation_row.addWidget(self.previous_button)
        navigation_row.addWidget(self.next_button)
        navigation_row.addWidget(self.take_button)
        controls.addLayout(navigation_row)

        list_host = QWidget()
        list_layout = QVBoxLayout(list_host)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.addWidget(QLabel("이번 주 콘티 · 절 선택 → Preview"))
        self.plan_list = QListWidget()
        self.plan_list.setAlternatingRowColors(True)
        list_layout.addWidget(self.plan_list, 1)
        layout.addWidget(controls_host)
        layout.addWidget(list_host, 1)

        self.open_bible_button.clicked.connect(self.open_bible)
        self.open_plan_button.clicked.connect(self.open_plan)
        self.save_plan_button.clicked.connect(self.save_plan)
        self.book_combo.currentIndexChanged.connect(self._book_changed)
        self.start_chapter_combo.currentIndexChanged.connect(self._start_chapter_changed)
        self.start_verse_combo.currentIndexChanged.connect(self._start_verse_changed)
        self.end_chapter_combo.currentIndexChanged.connect(self._end_chapter_changed)
        self.add_before_button.clicked.connect(
            lambda _checked=False: self.add_selected_range("before")
        )
        self.add_after_button.clicked.connect(
            lambda _checked=False: self.add_selected_range("after")
        )
        self.plan_list.currentRowChanged.connect(self._row_selected)
        self.remove_button.clicked.connect(self.remove_selected_range)
        self.move_up_button.clicked.connect(lambda: self.move_selected_range(-1))
        self.move_down_button.clicked.connect(lambda: self.move_selected_range(1))
        body_style_action.triggered.connect(
            lambda _checked=False: self.style_requested.emit()
        )
        reference_style_action.triggered.connect(
            lambda _checked=False: self.reference_style_requested.emit()
        )
        self.previous_button.clicked.connect(lambda: self.move_preview(-1))
        self.next_button.clicked.connect(lambda: self.move_preview(1))
        self.take_button.clicked.connect(self.take_requested)
        self._populate_books()

    def set_style(
        self,
        style: SubtitleStyle,
        key_color: str,
        *,
        refresh_preview: bool = True,
    ) -> None:
        self.subtitle_style = style
        self.key_color = key_color
        if refresh_preview:
            self._emit_preview()

    def set_group_header_color(self, color: str) -> None:
        self._group_header_color = QColor(color)
        for row in range(self.plan_list.count()):
            item = self.plan_list.item(row)
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and data and data[0] == "range":
                self._style_group_header(item)

    def _style_group_header(self, item: QListWidgetItem) -> None:
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setForeground(self._group_header_color)

    def set_repository(self, repository: BibleRepository, path: Path) -> None:
        for passage in self.ranges:
            repository.passage(passage)
        self._apply_repository(repository, path)

    def set_group_size(self, group_size: int, *, refresh_preview: bool = True) -> None:
        if group_size < 1:
            raise ValueError("Bible group size must be at least one")
        if group_size != self.group_size:
            self.group_size = group_size
            self._rebuild(refresh_preview=refresh_preview)

    def set_reference_style(
        self,
        style: SubtitleStyle,
        key_color: str,
        *,
        refresh_preview: bool = True,
    ) -> None:
        self.reference_style = style
        self.key_color = key_color
        if refresh_preview:
            self._emit_preview()

    def _apply_repository(self, repository: BibleRepository, path: Path) -> None:
        self.repository = repository
        self.bible_path = path.resolve()
        self.source_label.setText(self.bible_path.name)
        self.source_label.setToolTip(str(self.bible_path))
        self.open_bible_button.setToolTip(f"성경 본문 JSON\n{self.bible_path}")
        self._populate_books()
        self.bible_file_changed.emit(str(self.bible_path))

    def open_bible(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "성경 JSON 선택", str(self.bible_path or Path.home()), "JSON (*.json)"
        )
        if not selected:
            return
        try:
            self.set_repository(BibleRepository.load(Path(selected)), Path(selected))
        except (OSError, UnicodeError, KeyError, TypeError, ValueError) as error:
            QMessageBox.critical(self, "성경 파일 오류", str(error))
            return
        self.status_changed.emit("성경 JSON을 불러왔습니다.")

    def _populate_books(self) -> None:
        self.book_combo.blockSignals(True)
        self.book_combo.clear()
        if self.repository is not None:
            for book in self.repository.books:
                self.book_combo.addItem(book.name, book.id)
        self.book_combo.blockSignals(False)
        self._book_changed()

    def _book_changed(self) -> None:
        self.start_chapter_combo.clear()
        self.end_chapter_combo.clear()
        if self.repository is None or self.book_combo.currentIndex() < 0:
            return
        book = self.repository.book(str(self.book_combo.currentData()))
        for chapter in book.chapters:
            self.start_chapter_combo.addItem(str(chapter.number), chapter.number)
            self.end_chapter_combo.addItem(str(chapter.number), chapter.number)
        self._start_chapter_changed()
        self._end_chapter_changed()

    def _fill_verses(
        self,
        combo: TilePickerButton,
        chapter_combo: TilePickerButton,
    ) -> None:
        combo.clear()
        if self.repository is None or chapter_combo.currentIndex() < 0:
            return
        chapter = self.repository.chapter(
            str(self.book_combo.currentData()), int(chapter_combo.currentData())
        )
        for verse in chapter.verses:
            combo.addItem(verse.number_label, verse.number)

    def _start_chapter_changed(self) -> None:
        self._fill_verses(self.start_verse_combo, self.start_chapter_combo)
        if self.end_chapter_combo.currentIndex() < self.start_chapter_combo.currentIndex():
            self.end_chapter_combo.setCurrentIndex(self.start_chapter_combo.currentIndex())
        self._start_verse_changed()

    def _end_chapter_changed(self) -> None:
        self._fill_verses(self.end_verse_combo, self.end_chapter_combo)
        self._start_verse_changed()

    def _start_verse_changed(self) -> None:
        if (
            self.start_chapter_combo.currentIndex() < 0
            or self.end_chapter_combo.currentIndex() < 0
            or self.start_verse_combo.currentIndex() < 0
            or self.end_verse_combo.currentIndex() < 0
            or self.start_chapter_combo.currentData() != self.end_chapter_combo.currentData()
        ):
            return
        start = int(self.start_verse_combo.currentData())
        if int(self.end_verse_combo.currentData()) < start:
            target = self.end_verse_combo.findData(start)
            if target >= 0:
                self.end_verse_combo.setCurrentIndex(target)

    def add_selected_range(self, position: str = "after") -> None:
        if position not in {"before", "after"}:
            raise ValueError("position must be 'before' or 'after'")
        if self.repository is None or self.start_verse_combo.currentIndex() < 0:
            self.status_changed.emit("성경 JSON을 먼저 선택하십시오.")
            return
        try:
            passage = BiblePassageRange(
                BibleReference(
                    str(self.book_combo.currentData()),
                    int(self.start_chapter_combo.currentData()),
                    int(self.start_verse_combo.currentData()),
                ),
                BibleReference(
                    str(self.book_combo.currentData()),
                    int(self.end_chapter_combo.currentData()),
                    int(self.end_verse_combo.currentData()),
                ),
            )
            self.repository.passage(passage)
        except (KeyError, ValueError) as error:
            self.status_changed.emit(f"범위를 추가할 수 없습니다: {error}")
            return
        selected = self.plan_list.currentItem()
        selected_data = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        relative_to_cue = (
            isinstance(selected_data, tuple)
            and bool(selected_data)
            and selected_data[0] == "verse"
        )
        inserted_range_index = self._insert_range(passage, position)
        self._rebuild(refresh_preview=False)
        self._select_range(inserted_range_index)
        self._emit_preview()
        if relative_to_cue:
            direction = "앞" if position == "before" else "뒤"
            message = f"선택한 구절 {direction}에 범위를 추가했습니다."
        else:
            edge = "맨 앞" if position == "before" else "맨 뒤"
            message = f"콘티 {edge}에 범위를 추가했습니다."
        self.status_changed.emit(message)

    def _insert_range(self, passage: BiblePassageRange, position: str) -> int:
        """Insert a passage at the selected output-cue boundary."""
        if self.repository is None:
            raise ValueError("Bible repository is not loaded")
        selected = self.plan_list.currentItem()
        data = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        if not isinstance(data, tuple) or not data or data[0] != "verse":
            index = 0 if position == "before" else len(self.ranges)
            self.ranges.insert(index, passage)
            return index

        flat_index = int(data[1])
        range_index = int(data[2])
        cue = self._flat[flat_index]
        rows = self.repository.passage(self.ranges[range_index])
        cue_start = rows.index(cue[0])
        cue_end = rows.index(cue[-1]) + 1
        split_at = cue_start if position == "before" else cue_end
        prefix = rows[:split_at]
        suffix = rows[split_at:]
        replacement: list[BiblePassageRange] = []
        if prefix:
            replacement.append(self._range_from_rows(prefix))
        inserted_range_index = range_index + len(replacement)
        replacement.append(passage)
        if suffix:
            replacement.append(self._range_from_rows(suffix))
        self.ranges[range_index : range_index + 1] = replacement
        return inserted_range_index

    @staticmethod
    def _range_from_rows(
        rows: tuple[tuple[BibleReference, BibleVerse], ...],
    ) -> BiblePassageRange:
        first_reference, first_verse = rows[0]
        last_reference, last_verse = rows[-1]
        return BiblePassageRange(
            BibleReference(
                first_reference.book_id,
                first_reference.chapter,
                first_verse.number,
            ),
            BibleReference(
                last_reference.book_id,
                last_reference.chapter,
                last_verse.last_number,
            ),
        )

    def _select_range(self, range_index: int) -> None:
        for row in range(self.plan_list.count()):
            data = self.plan_list.item(row).data(Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and data[0] == "verse" and data[2] == range_index:
                self.preview_index = int(data[1])
                self._select_flat(self.preview_index)
                return

    def _rebuild(self, *, refresh_preview: bool = True) -> None:
        selected_reference = (
            self._flat[self.preview_index][0][0]
            if 0 <= self.preview_index < len(self._flat)
            else None
        )
        self.plan_list.blockSignals(True)
        self.plan_list.clear()
        self._flat.clear()
        if self.repository is not None:
            for range_index, passage in enumerate(self.ranges):
                book = self.repository.book(passage.start.book_id)
                header = QListWidgetItem(
                    f"{book.name} {passage.start.chapter}:{passage.start.verse} "
                    f"\N{EN DASH} "
                    f"{passage.end.chapter}:{passage.end.verse}"
                )
                header.setData(Qt.ItemDataRole.UserRole, ("range", range_index))
                header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self._style_group_header(header)
                self.plan_list.addItem(header)
                for cue in self._group_passage(self.repository.passage(passage)):
                    flat_index = len(self._flat)
                    self._flat.append(cue)
                    label = self._cue_label(cue)
                    text = " / ".join(verse.text for _reference, verse in cue)
                    item = QListWidgetItem(f"  {label}  {text}")
                    item.setData(Qt.ItemDataRole.UserRole, ("verse", flat_index, range_index))
                    self.plan_list.addItem(item)
        self.preview_index = -1
        if selected_reference is not None:
            self.preview_index = next(
                (
                    index
                    for index, cue in enumerate(self._flat)
                    if any(
                        reference.book_id == selected_reference.book_id
                        and reference.chapter == selected_reference.chapter
                        and verse.number <= selected_reference.verse <= verse.last_number
                        for reference, verse in cue
                    )
                ),
                -1,
            )
        if self.preview_index < 0 and self._flat:
            self.preview_index = 0
        if self.preview_index >= 0:
            self._select_flat(self.preview_index)
        self.plan_list.blockSignals(False)
        if refresh_preview and self.preview_index >= 0:
            self._emit_preview()

    def _group_passage(
        self,
        rows: tuple[tuple[BibleReference, BibleVerse], ...],
    ) -> tuple[tuple[tuple[BibleReference, BibleVerse], ...], ...]:
        cues: list[tuple[tuple[BibleReference, BibleVerse], ...]] = []
        current: list[tuple[BibleReference, BibleVerse]] = []
        covered_verses = 0
        for row in rows:
            reference, verse = row
            weight = verse.last_number - verse.number + 1
            previous_reference, previous_verse = current[-1] if current else (None, None)
            boundary = bool(
                current
                and (
                    previous_reference is None
                    or previous_verse is None
                    or reference.chapter != previous_reference.chapter
                    or reference.verse != previous_verse.last_number + 1
                    or covered_verses + weight > self.group_size
                )
            )
            if boundary:
                cues.append(tuple(current))
                current = []
                covered_verses = 0
            current.append(row)
            covered_verses += weight
            if covered_verses >= self.group_size:
                cues.append(tuple(current))
                current = []
                covered_verses = 0
        if current:
            cues.append(tuple(current))
        return tuple(cues)

    def _cue_label(
        self,
        cue: tuple[tuple[BibleReference, BibleVerse], ...],
    ) -> str:
        if self.repository is None or not cue:
            return ""
        first_reference, first_verse = cue[0]
        _last_reference, last_verse = cue[-1]
        book = self.repository.book(first_reference.book_id)
        if len(cue) == 1:
            verse_label = first_verse.number_label
        else:
            verse_label = f"{first_verse.number}-{last_verse.last_number}"
        return f"{book.name} {first_reference.chapter}:{verse_label}"

    def _row_selected(self, row: int) -> None:
        item = self.plan_list.item(row)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, tuple) and data and data[0] == "verse":
            self.preview_index = int(data[1])
            self._emit_preview()

    def _select_flat(self, index: int) -> None:
        for row in range(self.plan_list.count()):
            data = self.plan_list.item(row).data(Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and data[:2] == ("verse", index):
                self.plan_list.setCurrentRow(row)
                return

    def navigate(self, index: int) -> None:
        if not self._flat:
            return
        self.preview_index = max(0, min(index, len(self._flat) - 1))
        self._select_flat(self.preview_index)
        self._emit_preview()

    def move_preview(self, offset: int) -> None:
        self.navigate(self.preview_index + offset)

    def restore_preview(self) -> None:
        """Restore the weekly-plan cursor to Preview without changing Live."""
        self._emit_preview()

    @property
    def output_count(self) -> int:
        return len(self._flat)

    def mark_live(self) -> None:
        self.live_index = self.preview_index

    def _content_at(self, index: int, source: str = "bible") -> Content:
        if self.repository is None:
            raise ValueError("Bible repository is not loaded")
        cue = self._flat[index]
        reference, _first_verse = cue[0]
        return Content.subtitle(
            "\n".join(verse.text for _reference, verse in cue),
            index,
            self.subtitle_style,
            self.key_color,
            source=source,
            reference=reference.key,
            source_path=self.plan_path,
            label=self._cue_label(cue),
            label_style=self.reference_style,
        )

    def _emit_preview(self) -> None:
        if 0 <= self.preview_index < len(self._flat):
            self.preview_requested.emit(self._content_at(self.preview_index))

    def content_for_reference(self, value: str) -> Content:
        target = BibleReference.parse(value)
        for index, cue in enumerate(self._flat):
            if any(
                reference.book_id == target.book_id
                and reference.chapter == target.chapter
                and verse.number <= target.verse <= verse.last_number
                for reference, verse in cue
            ):
                self.preview_index = index
                self._select_flat(index)
                return self._content_at(index)
        raise KeyError(f"이번 주 성경 콘티에 {value}가 없습니다")

    def remove_selected_range(self) -> None:
        item = self.plan_list.currentItem()
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(data, tuple):
            return
        range_index = int(data[1] if data[0] == "range" else data[2])
        self.ranges.pop(range_index)
        self._rebuild()

    def move_selected_range(self, offset: int) -> None:
        item = self.plan_list.currentItem()
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(data, tuple):
            return
        index = int(data[1] if data[0] == "range" else data[2])
        destination = index + offset
        if not 0 <= destination < len(self.ranges):
            return
        self.ranges[index], self.ranges[destination] = self.ranges[destination], self.ranges[index]
        self._rebuild()

    def save_plan(self) -> bool:
        selected = str(self.plan_path or Path.home() / "이번주_성경_콘티.json")
        path_text, _ = QFileDialog.getSaveFileName(
            self, "성경 콘티 저장", selected, "JSON (*.json)"
        )
        if not path_text:
            return False
        return self.save_plan_path(Path(path_text))

    def save_plan_path(self, selected: Path) -> bool:
        path = selected.expanduser().resolve()
        source = self.bible_path.name if self.bible_path else ""
        payload: dict[str, Any] = {
            "schema_version": 1,
            "document_type": "church_presenter_bible_plan",
            "bible_source": source,
            "translation_id": self.repository.document.translation.id if self.repository else "",
            "ranges": [row.to_dict() for row in self.ranges],
        }
        atomic_write_json(path, payload)
        self.plan_path = path
        self.plan_label.setText(path.name)
        self.plan_label.setToolTip(str(path))
        self.save_plan_button.setToolTip(f"현재 성경 범위 콘티\n{path}")
        self.plan_file_changed.emit(str(path))
        self.status_changed.emit(f"성경 콘티 저장 완료: {path.name}")
        return True

    def open_plan(self) -> bool:
        selected, _ = QFileDialog.getOpenFileName(
            self, "성경 콘티 열기", str(self.plan_path or Path.home()), "JSON (*.json)"
        )
        if not selected:
            return False
        return self.load_plan_path(Path(selected))

    def load_plan_path(self, selected: Path) -> bool:
        path = selected.expanduser().resolve()
        try:
            payload = read_json_object(path)
            if (
                payload.get("document_type") != "church_presenter_bible_plan"
                or payload.get("schema_version") != 1
            ):
                raise ValueError("지원하지 않는 성경 콘티 파일입니다")
            source = payload.get("bible_source")
            repository = self.repository
            bible_path = self.bible_path
            if isinstance(source, str) and source:
                candidate = (path.parent / source).resolve()
                if candidate.is_file():
                    repository = BibleRepository.load(candidate)
                    bible_path = candidate
            rows = payload.get("ranges")
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise TypeError("ranges must be a list of objects")
            ranges = [BiblePassageRange.from_dict(row) for row in rows]
            if repository is None:
                raise ValueError("성경 JSON을 먼저 선택하십시오")
            for row in ranges:
                repository.passage(row)
        except (OSError, UnicodeError, KeyError, TypeError, ValueError) as error:
            QMessageBox.critical(self, "성경 콘티 파일 오류", str(error))
            return False
        if repository is not self.repository and bible_path is not None:
            # The candidate plan has already been validated against this repository.
            # Do not validate the currently open plan against the incoming source.
            self._apply_repository(repository, bible_path)
        self.ranges = ranges
        self.plan_path = path
        self.plan_label.setText(path.name)
        self.plan_label.setToolTip(str(path))
        self.open_plan_button.setToolTip(f"현재 성경 범위 콘티\n{path}")
        self.plan_file_changed.emit(str(path))
        self._rebuild()
        return True
