from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from church_presenter.domain.enums import ContentType
from church_presenter.domain.models import Content, PreviewPreset


class PreviewPresetPanel(QWidget):
    """Operator controls for named Broadcast/Venue Preview pairs."""

    save_requested = Signal(str)
    apply_requested = Signal(str)
    rename_requested = Signal(str, str)
    update_requested = Signal(str)
    delete_requested = Signal(str)
    move_requested = Signal(str, int)
    open_file_requested = Signal()
    save_file_as_requested = Signal()

    def __init__(self, presets: Iterable[PreviewPreset], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.presets: list[PreviewPreset] = list(presets)
        self.preset_buttons: dict[str, QPushButton] = {}
        self.update_buttons: dict[str, QPushButton] = {}
        self.applied_name = ""
        self.setMinimumWidth(230)
        self.setMaximumWidth(360)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        title = QLabel("예배 순서 Preview")
        title.setProperty("role", "sectionTitle")
        root.addWidget(title)

        self.file_label = QLabel("미저장")
        self.file_label.setObjectName("PreviewPresetFileLabel")
        self.file_label.setWordWrap(True)
        file_row = QHBoxLayout()
        self.open_file_button = QPushButton("파일 열기")
        self.save_file_as_button = QPushButton("다른 이름")
        for button in (
            self.open_file_button,
            self.save_file_as_button,
        ):
            file_row.addWidget(button)
        root.addWidget(self.file_label)
        root.addLayout(file_row)

        save_row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("PreviewPresetName")
        self.name_edit.setPlaceholderText("예: 1. 예배 시작")
        self.name_edit.setMaxLength(80)
        self.save_button = QPushButton("현재 Preview 저장")
        self.save_button.setObjectName("SavePreviewPreset")
        self.save_button.setProperty("variant", "primary")
        save_row.addWidget(self.name_edit, 1)
        save_row.addWidget(self.save_button)
        root.addLayout(save_row)

        self.preset_scroll = QScrollArea()
        self.preset_scroll.setWidgetResizable(True)
        self.preset_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.rows_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(6)
        self.preset_scroll.setWidget(self.rows_widget)
        root.addWidget(self.preset_scroll, 1)

        self.save_button.clicked.connect(self._request_save)
        self.name_edit.returnPressed.connect(self._request_save)
        self.open_file_button.clicked.connect(self.open_file_requested)
        self.save_file_as_button.clicked.connect(self.save_file_as_requested)
        self.set_presets(self.presets)

    def set_presets(self, presets: Iterable[PreviewPreset]) -> None:
        """Replace displayed buttons while preserving preset order."""
        self.presets = list(presets)
        self.preset_buttons.clear()
        self.update_buttons.clear()
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self.presets:
            empty = QLabel("저장된 순서가 없습니다.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.rows_layout.addWidget(empty)
        for index, preset in enumerate(self.presets):
            self.rows_layout.addWidget(self._preset_row(index, preset))
        self.rows_layout.addStretch()

    def _preset_row(self, index: int, preset: PreviewPreset) -> QWidget:
        row = QFrame()
        row.setObjectName("PreviewPresetRow")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        apply_button = QPushButton(f"{index + 1}. {preset.name}")
        apply_button.setObjectName("ApplyPreviewPreset")
        apply_button.setToolTip("송출과 현장 Preview에 적용")
        apply_button.setMinimumHeight(36)
        apply_button.setCheckable(True)
        apply_button.setChecked(preset.name == self.applied_name)
        apply_button.clicked.connect(
            lambda _checked=False, name=preset.name: self.apply_requested.emit(name)
        )
        self.preset_buttons[preset.name] = apply_button
        layout.addWidget(apply_button)
        summary = QLabel(
            f"송출 · {self._content_label(preset.broadcast_content)}\n"
            f"현장 · {self._content_label(preset.venue_content)}"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        controls = QHBoxLayout()
        up = QPushButton("▲")
        down = QPushButton("▼")
        update = QPushButton("저장")
        rename = QPushButton("이름 변경")
        delete = QPushButton("삭제")
        delete.setProperty("variant", "danger")
        update.setObjectName("UpdatePreviewPreset")
        update.setToolTip("현재 송출/현장 Preview 위치로 이 항목을 덮어쓰기")
        self.update_buttons[preset.name] = update
        up.setEnabled(index > 0)
        down.setEnabled(index + 1 < len(self.presets))
        up.clicked.connect(
            lambda _checked=False, name=preset.name: self.move_requested.emit(name, -1)
        )
        down.clicked.connect(
            lambda _checked=False, name=preset.name: self.move_requested.emit(name, 1)
        )
        update.clicked.connect(
            lambda _checked=False, name=preset.name: self.update_requested.emit(name)
        )
        rename.clicked.connect(
            lambda _checked=False, name=preset.name: self._request_rename(name)
        )
        delete.clicked.connect(
            lambda _checked=False, name=preset.name: self._request_delete(name)
        )
        for button in (up, down, update, rename, delete):
            controls.addWidget(button)
        layout.addLayout(controls)
        return row

    def _request_save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self.name_edit.setFocus()
            return
        self.save_requested.emit(name)

    def mark_saved(self) -> None:
        """Clear the name field after a successful save."""
        self.name_edit.clear()

    def set_file_path(self, path: str) -> None:
        """Show only the active worship-order JSON filename."""
        self.file_label.setText(Path(path).name if path else "미저장")
        self.file_label.setToolTip(path)

    def mark_applied(self, name: str) -> None:
        """Highlight the last preset copied into Preview."""
        self.applied_name = name
        for preset_name, button in self.preset_buttons.items():
            button.setChecked(preset_name == name)

    def _request_rename(self, old_name: str) -> None:
        new_name, accepted = QInputDialog.getText(
            self,
            "프리셋 이름 변경",
            "새 이름",
            text=old_name,
        )
        if accepted and new_name.strip() and new_name.strip() != old_name:
            self.rename_requested.emit(old_name, new_name.strip())

    def _request_delete(self, name: str) -> None:
        answer = QMessageBox.question(
            self,
            "프리셋 삭제",
            f"'{name}' 프리셋을 삭제하시겠습니까?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(name)

    @staticmethod
    def _content_label(content: Content) -> str:
        if content.kind is ContentType.BLACK:
            return "빈 화면 · 검정"
        if content.kind is ContentType.SOLID_COLOR:
            return f"빈 화면 · {content.background_color}"
        if content.kind is ContentType.SUBTITLE_KEY:
            position = content.subtitle_card_index
            return f"자막 카드 · {position + 1 if position is not None else '미지정'}"
        if content.kind is ContentType.PDF_PAGE:
            page = content.pdf_page
            return f"PDF · {page + 1 if page is not None else '미지정'}쪽"
        if content.kind is ContentType.VIDEO:
            return "영상 · 현재 선택 파일"
        return content.kind.value
