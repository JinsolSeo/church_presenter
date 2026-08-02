from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from church_presenter.domain.song import SongDocument, SongSection, SongSectionType
from church_presenter.services.song_service import save_song


@dataclass(slots=True)
class _DraftSection:
    id: str
    type: SongSectionType
    label: str
    lyrics: str = ""


class SongJsonDialog(QDialog):
    """Create a reusable sectioned song JSON file."""

    def __init__(self, destination_folder: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("곡 JSON 만들기")
        self.resize(820, 620)
        self.destination_folder = destination_folder.expanduser()
        self.saved_path: Path | None = None
        self.sections: list[_DraftSection] = []
        self._loading_section = False

        root = QVBoxLayout(self)
        metadata = QFormLayout()
        self.title_edit = QLineEdit()
        metadata.addRow("곡 제목", self.title_edit)
        root.addLayout(metadata)

        root.addWidget(QLabel("가사 구성 · 섹션을 선택하고 오른쪽에 가사를 입력하세요"))
        splitter = QSplitter(Qt.Orientation.Horizontal)
        section_host = QWidget()
        section_layout = QVBoxLayout(section_host)
        section_layout.setContentsMargins(0, 0, 0, 0)
        self.section_list = QListWidget()
        section_layout.addWidget(self.section_list, 1)
        add_row = QHBoxLayout()
        self.add_type_combo = QComboBox()
        for section_type in SongSectionType:
            self.add_type_combo.addItem(section_type.display_name, section_type)
        self.add_section_button = QPushButton("섹션 추가")
        self.remove_section_button = QPushButton("삭제")
        add_row.addWidget(self.add_type_combo, 1)
        add_row.addWidget(self.add_section_button)
        add_row.addWidget(self.remove_section_button)
        section_layout.addLayout(add_row)
        move_row = QHBoxLayout()
        self.move_up_button = QPushButton("▲ 위")
        self.move_down_button = QPushButton("▼ 아래")
        move_row.addWidget(self.move_up_button)
        move_row.addWidget(self.move_down_button)
        section_layout.addLayout(move_row)

        editor_host = QWidget()
        editor_layout = QVBoxLayout(editor_host)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        label_row = QHBoxLayout()
        label_row.addWidget(QLabel("표시 이름"))
        self.section_label_edit = QLineEdit()
        label_row.addWidget(self.section_label_edit, 1)
        editor_layout.addLayout(label_row)
        self.lyrics_edit = QPlainTextEdit()
        self.lyrics_edit.setPlaceholderText("가사 한 줄마다 줄바꿈하세요")
        editor_layout.addWidget(self.lyrics_edit, 1)
        splitter.addWidget(section_host)
        splitter.addWidget(editor_host)
        splitter.setSizes([280, 520])
        root.addWidget(splitter, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("JSON 저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        root.addWidget(buttons)

        self.section_list.currentRowChanged.connect(self._section_selected)
        self.section_label_edit.textChanged.connect(self._section_edited)
        self.lyrics_edit.textChanged.connect(self._section_edited)
        self.add_section_button.clicked.connect(self._add_selected_type)
        self.remove_section_button.clicked.connect(self._remove_section)
        self.move_up_button.clicked.connect(lambda: self._move_section(-1))
        self.move_down_button.clicked.connect(lambda: self._move_section(1))
        buttons.button(QDialogButtonBox.StandardButton.Save).clicked.connect(self._save)
        buttons.rejected.connect(self.reject)

        self._add_section(SongSectionType.VERSE)
        self._add_section(SongSectionType.CHORUS)
        self.section_list.setCurrentRow(0)

    def _next_section_id(self, section_type: SongSectionType) -> str:
        used = {section.id for section in self.sections}
        if section_type is SongSectionType.VERSE:
            number = 1
            while f"verse_{number}" in used:
                number += 1
            return f"verse_{number}"
        prefix = section_type.value
        if prefix not in used:
            return prefix
        number = 2
        while f"{prefix}_{number}" in used:
            number += 1
        return f"{prefix}_{number}"

    def _add_selected_type(self) -> None:
        try:
            section_type = SongSectionType(self.add_type_combo.currentData())
        except (TypeError, ValueError):
            QMessageBox.warning(self, "섹션 추가", "추가할 섹션 종류를 선택하십시오.")
            return
        self._add_section(section_type)

    def _add_section(self, section_type: SongSectionType) -> None:
        section_id = self._next_section_id(section_type)
        label = (
            f"Verse {section_id.rsplit('_', 1)[-1]}"
            if section_type is SongSectionType.VERSE
            else section_type.display_name
        )
        self.sections.append(_DraftSection(section_id, section_type, label))
        self.section_list.addItem(f"{label} · {section_id}")
        self.section_list.setCurrentRow(len(self.sections) - 1)

    def _section_selected(self, row: int) -> None:
        self._loading_section = True
        enabled = 0 <= row < len(self.sections)
        self.section_label_edit.setEnabled(enabled)
        self.lyrics_edit.setEnabled(enabled)
        if enabled:
            section = self.sections[row]
            self.section_label_edit.setText(section.label)
            self.lyrics_edit.setPlainText(section.lyrics)
        else:
            self.section_label_edit.clear()
            self.lyrics_edit.clear()
        self._loading_section = False

    def _section_edited(self) -> None:
        if self._loading_section:
            return
        row = self.section_list.currentRow()
        if not 0 <= row < len(self.sections):
            return
        section = self.sections[row]
        section.label = self.section_label_edit.text()
        section.lyrics = self.lyrics_edit.toPlainText()
        self.section_list.item(row).setText(f"{section.label or '(이름 없음)'} · {section.id}")

    def _remove_section(self) -> None:
        row = self.section_list.currentRow()
        if not 0 <= row < len(self.sections):
            return
        self.sections.pop(row)
        self.section_list.takeItem(row)
        self.section_list.setCurrentRow(min(row, len(self.sections) - 1))

    def _move_section(self, offset: int) -> None:
        row = self.section_list.currentRow()
        destination = row + offset
        if not (0 <= row < len(self.sections) and 0 <= destination < len(self.sections)):
            return
        self.sections[row], self.sections[destination] = (
            self.sections[destination],
            self.sections[row],
        )
        item = self.section_list.takeItem(row)
        self.section_list.insertItem(destination, item)
        self.section_list.setCurrentRow(destination)

    def document(self) -> SongDocument:
        title = self.title_edit.text().strip()
        invalid_filename_characters = '<>:"/\\|?*\x00'
        if (
            not title
            or title in {".", ".."}
            or title.endswith((" ", "."))
            or any(character in title for character in invalid_filename_characters)
        ):
            raise ValueError("곡 제목에 파일 이름으로 사용할 수 없는 문자가 있습니다.")
        return SongDocument(
            id=title,
            title=title,
            artist="",
            sections=tuple(
                SongSection(
                    section.id,
                    section.type,
                    section.label.strip(),
                    tuple(
                        line.strip()
                        for line in section.lyrics.splitlines()
                        if line.strip()
                    ),
                )
                for section in self.sections
            ),
            default_sequence=tuple(section.id for section in self.sections),
        )

    def _save(self) -> None:
        try:
            song = self.document()
        except (KeyError, TypeError, ValueError) as error:
            QMessageBox.warning(self, "곡 JSON 확인", str(error))
            return
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "곡 JSON 저장",
            str(self.destination_folder / f"{song.title}.json"),
            "Song JSON (*.json)",
        )
        if not selected:
            return
        destination = Path(selected).parent / f"{song.title}.json"
        try:
            self.saved_path = save_song(destination, song)
        except OSError as error:
            QMessageBox.critical(self, "곡 JSON 저장 실패", str(error))
            return
        self.accept()
