from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from church_presenter.domain.models import Content, SubtitleStyle
from church_presenter.domain.song import SongCue, SongDocument, SongPlanEntry, SongSectionType
from church_presenter.services.song_service import (
    load_song,
    load_song_plan,
    save_song_plan,
)
from church_presenter.ui.dialogs.song_json_dialog import SongJsonDialog


class SubtitlePanel(QWidget):
    """Build and navigate a weekly praise plan from sectioned song JSON files."""

    preview_requested = Signal(object)
    take_requested = Signal()
    style_requested = Signal()
    status_changed = Signal(str)
    settings_changed = Signal(int, str, str)

    def __init__(
        self,
        style: SubtitleStyle,
        key_color: str,
        group_size: int = 2,
        song_folder: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.subtitle_style = style
        self.key_color = key_color
        self.group_size = max(1, group_size)
        self.song_folder = song_folder
        self.plan_path: Path | None = None
        self.library: dict[Path, SongDocument] = {}
        self.entries: list[SongPlanEntry] = []
        self._flat: list[SongCue] = []
        self.preview_index = -1
        self.live_index = -1
        self.is_modified = False
        self._card_live_background = QColor(Qt.GlobalColor.red)
        self._card_preview_background = QColor(Qt.GlobalColor.darkCyan)
        self._card_text = QColor(Qt.GlobalColor.black)
        self._card_active_text = QColor(Qt.GlobalColor.white)

        layout = QHBoxLayout(self)
        controls_host = QWidget()
        controls_host.setMinimumWidth(350)
        controls_host.setMaximumWidth(470)
        controls = QVBoxLayout(controls_host)
        controls.setContentsMargins(0, 0, 0, 0)

        file_row = QHBoxLayout()
        self.open_song_button = QPushButton("곡 JSON")
        self.open_song_button.setProperty("variant", "primary")
        self.open_plan_button = QPushButton("콘티 열기")
        self.save_plan_button = QPushButton("콘티 저장")
        self.create_song_button = QPushButton("곡 만들기")
        self.style_button = QPushButton("Style")
        file_row.addWidget(self.open_song_button)
        file_row.addWidget(self.open_plan_button)
        file_row.addWidget(self.save_plan_button)
        file_row.addWidget(self.create_song_button)
        file_row.addWidget(self.style_button)
        controls.addLayout(file_row)

        song_row = QHBoxLayout()
        song_row.addWidget(QLabel("곡 선택"))
        self.song_combo = QComboBox()
        self.song_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.song_combo.setMinimumContentsLength(18)
        self.song_combo.setPlaceholderText("곡 JSON을 선택하세요")
        song_row.addWidget(self.song_combo, 1)
        controls.addLayout(song_row)

        selection_row = QHBoxLayout()
        self.section_list = QListWidget()
        self.section_list.setMinimumHeight(72)
        self.section_list.setToolTip("추가할 Verse, Chorus, Bridge를 선택하세요")
        selection_row.addWidget(self.section_list, 1)

        action_host = QWidget()
        action_host.setMinimumWidth(76)
        action_host.setMaximumWidth(92)
        actions = QVBoxLayout(action_host)
        actions.setContentsMargins(0, 0, 0, 0)
        self.add_button = QPushButton("추가")
        self.add_button.setProperty("variant", "primary")
        self.remove_button = QPushButton("삭제")
        self.move_up_button = QPushButton("▲")
        self.move_down_button = QPushButton("▼")
        actions.addWidget(self.add_button)
        actions.addWidget(self.remove_button)
        move_row = QHBoxLayout()
        move_row.setContentsMargins(0, 0, 0, 0)
        move_row.addWidget(self.move_up_button)
        move_row.addWidget(self.move_down_button)
        actions.addLayout(move_row)
        actions.addStretch()
        selection_row.addWidget(action_host)
        controls.addLayout(selection_row, 1)

        navigation_row = QHBoxLayout()
        self.previous_button = QPushButton("◀ 이전")
        self.next_button = QPushButton("다음 ▶")
        self.take_button = QPushButton("TAKE")
        self.take_button.setProperty("variant", "take")
        navigation_row.addWidget(self.previous_button)
        navigation_row.addWidget(self.next_button)
        navigation_row.addWidget(self.take_button)
        controls.addLayout(navigation_row)

        plan_host = QWidget()
        plan_layout = QVBoxLayout(plan_host)
        plan_layout.setContentsMargins(0, 0, 0, 0)
        plan_layout.addWidget(QLabel("이번 주 찬양 콘티 · 카드 선택 → Preview"))
        self.plan_list = QListWidget()
        self.plan_list.setObjectName("SubtitleCardList")
        self.plan_list.setAlternatingRowColors(True)
        self.plan_list.setWordWrap(True)
        self.plan_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.plan_list.setUniformItemSizes(False)
        self.plan_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        plan_layout.addWidget(self.plan_list, 1)
        self.card_list = self.plan_list

        layout.addWidget(controls_host, 3)
        layout.addWidget(plan_host, 5)

        self.open_song_button.clicked.connect(self.open_song_files)
        self.open_plan_button.clicked.connect(self.open_plan)
        self.save_plan_button.clicked.connect(self.save_plan)
        self.create_song_button.clicked.connect(self.create_song_file)
        self.song_combo.currentIndexChanged.connect(self._song_changed)
        self.add_button.clicked.connect(self.add_selected_sections)
        self.remove_button.clicked.connect(self.remove_selected_entry)
        self.move_up_button.clicked.connect(lambda: self.move_selected_entry(-1))
        self.move_down_button.clicked.connect(lambda: self.move_selected_entry(1))
        self.style_button.clicked.connect(self.style_requested)
        self.previous_button.clicked.connect(lambda: self.move_preview(-1))
        self.next_button.clicked.connect(lambda: self.move_preview(1))
        self.take_button.clicked.connect(self.take_requested)
        self.plan_list.currentRowChanged.connect(self._row_selected)
        self._refresh_labels()

    @property
    def output_count(self) -> int:
        return len(self._flat)

    def set_card_theme(
        self,
        *,
        live_background: str,
        preview_background: str,
        text: str,
        active_text: str,
    ) -> None:
        self._card_live_background = QColor(live_background)
        self._card_preview_background = QColor(preview_background)
        self._card_text = QColor(text)
        self._card_active_text = QColor(active_text)
        self._refresh_labels()

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

    def set_group_size(self, value: int) -> None:
        if value < 1:
            raise ValueError("song group size must be at least one")
        if value != self.group_size:
            self.group_size = value
            self.live_index = -1
            self._rebuild()
            self._emit_settings_changed()

    def open_song_files(self) -> None:
        selected, _ = QFileDialog.getOpenFileNames(
            self,
            "곡 JSON 선택",
            str(self.song_folder or Path.home()),
            "Song JSON (*.json)",
        )
        if selected:
            self.load_song_paths([Path(path) for path in selected])

    def create_song_file(self) -> None:
        dialog = SongJsonDialog(self.song_folder or Path.home(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.saved_path is not None:
            self.load_song_paths([dialog.saved_path])

    def load_song_paths(self, paths: list[Path]) -> bool:
        try:
            loaded = [
                (path.expanduser().resolve(), load_song(path.expanduser().resolve()))
                for path in paths
            ]
            loaded_paths = {loaded_path for loaded_path, _song in loaded}
            known_ids = {
                song.id: path
                for path, song in self.library.items()
                if path not in loaded_paths
            }
            for path, song in loaded:
                if song.id in known_ids and known_ids[song.id] != path:
                    raise ValueError(
                        f"같은 곡 ID를 사용하는 다른 파일이 있습니다: {song.id}"
                    )
                known_ids[song.id] = path
        except (OSError, UnicodeError, KeyError, TypeError, ValueError) as error:
            QMessageBox.critical(self, "곡 JSON 오류", str(error))
            return False
        if not loaded:
            return False
        for path, song in loaded:
            self.library[path] = song
        self.song_folder = loaded[-1][0].parent
        self._refresh_song_combo(selected_path=loaded[-1][0])
        self._emit_settings_changed()
        self.status_changed.emit(f"곡 JSON {len(loaded)}개를 불러왔습니다.")
        return True

    def _refresh_song_combo(self, selected_path: Path | None = None) -> None:
        current = selected_path or self._current_song_path()
        self.song_combo.blockSignals(True)
        self.song_combo.clear()
        for path, song in self.library.items():
            self.song_combo.addItem(song.title, str(path))
        if current is not None:
            target = self.song_combo.findData(str(current))
            if target >= 0:
                self.song_combo.setCurrentIndex(target)
        self.song_combo.blockSignals(False)
        self._song_changed()

    def _current_song_path(self) -> Path | None:
        value = self.song_combo.currentData()
        return Path(str(value)) if isinstance(value, str) and value else None

    def _current_song(self) -> tuple[Path, SongDocument] | None:
        path = self._current_song_path()
        if path is None:
            return None
        song = self.library.get(path)
        return (path, song) if song is not None else None

    def _song_changed(self) -> None:
        self.section_list.clear()
        current = self._current_song()
        if current is None:
            self.song_combo.setToolTip("곡 JSON을 선택하세요")
            return
        path, song = current
        self.song_combo.setToolTip(f"{path}\n불러온 곡 {len(self.library)}개")
        chorus_found = False
        for section in song.sections:
            item = QListWidgetItem(
                f"{section.label} · {section.type.display_name} · {len(section.lines)}줄"
            )
            item.setData(Qt.ItemDataRole.UserRole, section.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = section.type is SongSectionType.CHORUS
            chorus_found = chorus_found or checked
            item.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )
            self.section_list.addItem(item)
        if not chorus_found and self.section_list.count():
            self.section_list.item(0).setCheckState(Qt.CheckState.Checked)

    def add_selected_sections(self) -> None:
        current = self._current_song()
        if current is None:
            self.status_changed.emit("곡 JSON을 먼저 선택하십시오.")
            return
        path, song = current
        sequence = tuple(
            str(self.section_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.section_list.count())
            if self.section_list.item(row).checkState() is Qt.CheckState.Checked
        )
        if not sequence:
            self.status_changed.emit("추가할 Verse, Chorus 또는 Bridge를 선택하십시오.")
            return
        if set(sequence) == {section.id for section in song.sections}:
            sequence = song.default_sequence
        self._add_entry(SongPlanEntry.create(path, song, sequence))

    def _add_entry(self, entry: SongPlanEntry) -> None:
        self.entries.append(entry)
        self.is_modified = True
        self._rebuild(refresh_preview=False)
        self._select_entry(len(self.entries) - 1)
        self._emit_preview()
        self.status_changed.emit(f"찬양 콘티에 {entry.song.title}을(를) 추가했습니다.")

    def remove_selected_entry(self) -> None:
        entry_index = self._selected_entry_index()
        if entry_index is None:
            return
        removed = self.entries.pop(entry_index)
        self.is_modified = True
        self._rebuild()
        self.status_changed.emit(f"찬양 콘티에서 {removed.song.title}을(를) 삭제했습니다.")

    def move_selected_entry(self, offset: int) -> None:
        entry_index = self._selected_entry_index()
        if entry_index is None:
            return
        destination = entry_index + offset
        if not 0 <= destination < len(self.entries):
            return
        self.entries[entry_index], self.entries[destination] = (
            self.entries[destination],
            self.entries[entry_index],
        )
        self.is_modified = True
        self._rebuild(refresh_preview=False)
        self._select_entry(destination)
        self._emit_preview()

    def _selected_entry_index(self) -> int | None:
        item = self.plan_list.currentItem()
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if isinstance(data, tuple) and len(data) >= 3 and data[0] == "cue":
            return int(data[2])
        return None

    def _rebuild(self, *, refresh_preview: bool = True) -> None:
        selected_reference = (
            self._flat[self.preview_index].reference
            if 0 <= self.preview_index < len(self._flat)
            else ""
        )
        self.plan_list.blockSignals(True)
        self.plan_list.clear()
        self._flat.clear()
        for entry_index, entry in enumerate(self.entries):
            sequence_labels = " → ".join(
                entry.song.section(section_id).label for section_id in entry.sequence
            )
            header = QListWidgetItem(f"{entry.song.title} · {sequence_labels}")
            header.setData(Qt.ItemDataRole.UserRole, ("entry", entry_index))
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.plan_list.addItem(header)
            for occurrence, section_id in enumerate(entry.sequence):
                section = entry.song.section(section_id)
                for line_start in range(0, len(section.lines), self.group_size):
                    lines = section.lines[line_start : line_start + self.group_size]
                    cue = SongCue(
                        entry.entry_id,
                        occurrence,
                        section.id,
                        line_start,
                        line_start + len(lines),
                        "\n".join(lines),
                    )
                    flat_index = len(self._flat)
                    self._flat.append(cue)
                    text = " / ".join(lines)
                    item = QListWidgetItem(f"  {section.label} · {text}")
                    item.setData(
                        Qt.ItemDataRole.UserRole,
                        ("cue", flat_index, entry_index),
                    )
                    self.plan_list.addItem(item)
        self.preview_index = -1
        if selected_reference:
            self.preview_index = self._index_for_reference(selected_reference)
        if self.preview_index < 0 and self._flat:
            self.preview_index = 0
        if self.preview_index >= 0:
            self._select_flat(self.preview_index)
        self.plan_list.blockSignals(False)
        self._refresh_labels()
        if refresh_preview:
            self._emit_preview()

    def _row_selected(self, row: int) -> None:
        item = self.plan_list.item(row)
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if isinstance(data, tuple) and data and data[0] == "cue":
            self.preview_index = int(data[1])
            self._refresh_labels()
            self._emit_preview()

    def _select_flat(self, index: int) -> None:
        for row in range(self.plan_list.count()):
            data = self.plan_list.item(row).data(Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and data[:2] == ("cue", index):
                self.plan_list.setCurrentRow(row)
                return

    def _select_entry(self, entry_index: int) -> None:
        for row in range(self.plan_list.count()):
            data = self.plan_list.item(row).data(Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and data[0] == "cue" and data[2] == entry_index:
                self.preview_index = int(data[1])
                self._select_flat(self.preview_index)
                return

    def navigate(self, destination: int) -> None:
        if not self._flat:
            return
        self.preview_index = max(0, min(destination, len(self._flat) - 1))
        self._select_flat(self.preview_index)
        self._refresh_labels()
        self._emit_preview()

    def set_preview_position(self, destination: int) -> None:
        if not 0 <= destination < len(self._flat):
            return
        self.preview_index = destination
        self.plan_list.blockSignals(True)
        self._select_flat(destination)
        self.plan_list.blockSignals(False)
        self._refresh_labels()

    def move_preview(self, offset: int) -> None:
        self.navigate(self.preview_index + offset)

    def restore_preview(self) -> None:
        self._emit_preview()

    def mark_live(self) -> None:
        self.live_index = self.preview_index
        self._refresh_labels()

    def _content_at(self, index: int) -> Content:
        cue = self._flat[index]
        return Content.subtitle(
            cue.text,
            index,
            self.subtitle_style,
            self.key_color,
            source="praise",
            reference=cue.reference,
        )

    def _emit_preview(self) -> None:
        if 0 <= self.preview_index < len(self._flat):
            self.preview_requested.emit(self._content_at(self.preview_index))

    def _index_for_reference(self, value: str) -> int:
        entry_id, occurrence, line_index = SongCue.parse_reference(value)
        return next(
            (
                index
                for index, cue in enumerate(self._flat)
                if cue.entry_id == entry_id
                and cue.occurrence == occurrence
                and cue.line_start <= line_index < cue.line_end
            ),
            -1,
        )

    def content_for_reference(self, value: str) -> Content:
        index = self._index_for_reference(value)
        if index < 0:
            raise KeyError(f"현재 찬양 콘티에 {value}가 없습니다")
        self.preview_index = index
        self._select_flat(index)
        self._refresh_labels()
        return self._content_at(index)

    def _refresh_labels(self) -> None:
        selected_card_live = self.live_index >= 0 and self.live_index == self.preview_index
        if self.plan_list.property("selectedCardLive") != selected_card_live:
            self.plan_list.setProperty("selectedCardLive", selected_card_live)
            style = self.plan_list.style()
            style.unpolish(self.plan_list)
            style.polish(self.plan_list)
        for row in range(self.plan_list.count()):
            item = self.plan_list.item(row)
            data = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(data, tuple) or not data or data[0] != "cue":
                continue
            index = int(data[1])
            cue = self._flat[index]
            section = self.entries[int(data[2])].song.section(cue.section_id)
            labels: list[str] = []
            if index == self.live_index:
                labels.append("LIVE")
            if index == self.preview_index:
                labels.append("PREVIEW")
            prefix = f"[{' + '.join(labels)}]  " if labels else "  "
            item.setText(prefix + f"{section.label} · {' / '.join(cue.text.splitlines())}")
            if index == self.live_index:
                item.setBackground(self._card_live_background)
                item.setForeground(self._card_active_text)
            elif index == self.preview_index:
                item.setBackground(self._card_preview_background)
                item.setForeground(self._card_active_text)
            else:
                item.setBackground(Qt.GlobalColor.transparent)
                item.setForeground(self._card_text)

    def save_plan(self) -> bool:
        if self.plan_path is None:
            selected, _ = QFileDialog.getSaveFileName(
                self,
                "찬양 콘티 저장",
                str((self.song_folder or Path.home()) / "이번주_찬양_콘티.json"),
                "JSON (*.json)",
            )
            if not selected:
                return False
            path = Path(selected)
        else:
            path = self.plan_path
        try:
            self.plan_path = save_song_plan(path, self.entries)
        except OSError as error:
            QMessageBox.critical(self, "찬양 콘티 저장 실패", str(error))
            return False
        self.is_modified = False
        self._emit_settings_changed()
        self.status_changed.emit(f"찬양 콘티 저장 완료: {self.plan_path.name}")
        return True

    def open_plan(self) -> bool:
        if not self.confirm_discard_changes():
            return False
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "찬양 콘티 열기",
            str(self.plan_path or self.song_folder or Path.home()),
            "JSON (*.json)",
        )
        return bool(selected) and self.load_plan_path(Path(selected), warn=False)

    def load_plan_path(self, path: Path, *, warn: bool = True) -> bool:
        if warn and not self.confirm_discard_changes():
            return False
        source = path.expanduser().resolve()
        try:
            entries = load_song_plan(source)
        except (OSError, UnicodeError, KeyError, TypeError, ValueError) as error:
            QMessageBox.critical(self, "찬양 콘티 오류", str(error))
            return False
        self.entries = entries
        for entry in entries:
            self.library[entry.song_path] = entry.song
        self.plan_path = source
        self.song_folder = entries[0].song_path.parent if entries else source.parent
        self.is_modified = False
        self.live_index = -1
        self._refresh_song_combo()
        self._rebuild()
        self._emit_settings_changed()
        self.status_changed.emit(f"찬양 콘티를 불러왔습니다: {source.name}")
        return True

    def confirm_discard_changes(self) -> bool:
        if not self.is_modified:
            return True
        answer = QMessageBox.question(
            self,
            "저장하지 않은 찬양 콘티",
            "찬양 콘티 변경사항을 저장하시겠습니까?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            return self.save_plan()
        return answer == QMessageBox.StandardButton.No

    def _emit_settings_changed(self) -> None:
        self.settings_changed.emit(
            self.group_size,
            str(self.plan_path or ""),
            str(self.song_folder or ""),
        )
