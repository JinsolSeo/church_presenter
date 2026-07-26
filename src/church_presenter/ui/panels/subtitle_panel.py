from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from church_presenter.domain.models import Content, SubtitleDocument, SubtitleStyle
from church_presenter.services.subtitle_service import load_subtitle, save_subtitle
from church_presenter.ui.dialogs.subtitle_merge_dialog import SubtitleMergeDialog


class SubtitlePanel(QWidget):
    """Grouped-card navigation with source-line editing."""

    preview_requested = Signal(object)
    take_requested = Signal()
    style_requested = Signal()
    document_changed = Signal(object)

    def __init__(
        self,
        style: SubtitleStyle,
        key_color: str,
        group_size: int = 2,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.document = SubtitleDocument(group_size=group_size)
        self.subtitle_style = style
        self.key_color = key_color
        self.preview_index = -1
        self.live_index = -1
        self._selected_source_index = -1
        self._card_live_background = QColor(Qt.GlobalColor.red)
        self._card_preview_background = QColor(Qt.GlobalColor.darkCyan)
        self._card_text = QColor(Qt.GlobalColor.black)
        self._card_active_text = QColor(Qt.GlobalColor.white)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.file_label = QLabel("자막 파일 없음")
        self.file_label.setMinimumWidth(1)
        self.file_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.open_button = QPushButton("TXT 열기")
        self.open_button.setProperty("variant", "primary")
        self.save_button = QPushButton("저장")
        save_as_button = QPushButton("다른 이름으로 저장")
        self.reload_button = QPushButton("다시 불러오기")
        style_button = QPushButton("자막 스타일 설정")
        self.merge_button = QPushButton("자막 합치기")
        for widget in (
            self.file_label,
            self.open_button,
            self.save_button,
            save_as_button,
            self.reload_button,
            style_button,
            self.merge_button,
        ):
            toolbar.addWidget(widget)
        toolbar.setStretch(0, 1)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("출력 카드 (파생 데이터)"))
        self.card_list = QListWidget()
        self.card_list.setObjectName("SubtitleCardList")
        self.card_list.setAlternatingRowColors(True)
        left_layout.addWidget(self.card_list)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("원본 한 줄 편집 (source of truth)"))
        self.line_list = QListWidget()
        right_layout.addWidget(self.line_list)
        self.line_edit = QLineEdit()
        self.line_edit.setPlaceholderText("선택한 원본 줄을 편집하고 Enter")
        right_layout.addWidget(self.line_edit)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.add_line_button = QPushButton("줄 추가")
        self.delete_line_button = QPushButton("줄 삭제")
        self.delete_line_button.setProperty("variant", "danger")
        self.move_up_button = QPushButton("위로")
        self.move_down_button = QPushButton("아래로")
        for button in (
            self.add_line_button,
            self.delete_line_button,
            self.move_up_button,
            self.move_down_button,
        ):
            button.setMaximumWidth(110)
            actions.addWidget(button)
        right_layout.addLayout(actions)
        splitter.addWidget(right)
        splitter.setSizes([520, 460])
        layout.addWidget(splitter)

        self.open_button.clicked.connect(self.open_file)
        self.save_button.clicked.connect(self.save)
        save_as_button.clicked.connect(self.save_as)
        self.reload_button.clicked.connect(self.reload)
        style_button.clicked.connect(self.style_requested)
        self.merge_button.clicked.connect(self.open_merge_dialog)
        self.card_list.currentRowChanged.connect(self._card_selected)
        self.line_list.currentRowChanged.connect(self._source_selected)
        self.line_edit.returnPressed.connect(self._commit_line_edit)
        self.add_line_button.clicked.connect(self._add_line)
        self.delete_line_button.clicked.connect(self._delete_line)
        self.move_up_button.clicked.connect(lambda: self._move_line(-1))
        self.move_down_button.clicked.connect(lambda: self._move_line(1))
        self._refresh()

    def set_card_theme(
        self,
        *,
        live_background: str,
        preview_background: str,
        text: str,
        active_text: str,
    ) -> None:
        """Apply semantic theme colors to subtitle navigation cards."""
        self._card_live_background = QColor(live_background)
        self._card_preview_background = QColor(preview_background)
        self._card_text = QColor(text)
        self._card_active_text = QColor(active_text)
        self._refresh_labels()

    def set_style(self, style: SubtitleStyle, key_color: str) -> None:
        self.subtitle_style = style
        self.key_color = key_color
        if self.preview_index >= 0:
            self._emit_preview()

    def load_path(self, path: Path, *, warn: bool = True) -> bool:
        if warn and not self.confirm_discard_changes():
            return False
        source = path.expanduser().resolve()
        try:
            document = load_subtitle(source, self.document.group_size)
        except (OSError, UnicodeError) as error:
            QMessageBox.critical(self, "자막 파일 오류", str(error))
            return False
        self.document = document
        self.file_label.setText(str(source))
        self.file_label.setToolTip(str(source))
        self.preview_index = 0 if document.cards else -1
        self.live_index = -1
        self._refresh()
        if self.preview_index >= 0:
            self._emit_preview()
        self.document_changed.emit(self.document)
        return True

    def open_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "자막 파일 선택",
            str(self.document.path.parent if self.document.path else Path.home()),
            "Text files (*.txt)",
        )
        if selected:
            self.load_path(Path(selected))

    def open_merge_dialog(self) -> None:
        initial_folder = self.document.path.parent if self.document.path else None
        dialog = SubtitleMergeDialog(
            initial_folder,
            self.document.group_size,
            self,
        )
        dialog.exec()

    def save(self) -> bool:
        if self.document.path is None:
            return self.save_as()
        try:
            save_subtitle(self.document)
        except OSError as error:
            QMessageBox.critical(self, "저장 실패", str(error))
            return False
        self._refresh_labels()
        self.document_changed.emit(self.document)
        return True

    def save_as(self) -> bool:
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "자막 다른 이름으로 저장",
            str(self.document.path or Path.home() / "subtitles.txt"),
            "Text files (*.txt)",
        )
        if not selected:
            return False
        try:
            path = save_subtitle(self.document, Path(selected))
        except OSError as error:
            QMessageBox.critical(self, "저장 실패", str(error))
            return False
        self.file_label.setText(str(path))
        self.file_label.setToolTip(str(path))
        self._refresh_labels()
        self.document_changed.emit(self.document)
        return True

    def reload(self) -> bool:
        if self.document.path is None:
            return False
        return self.load_path(self.document.path)

    def confirm_discard_changes(self) -> bool:
        if not self.document.is_modified:
            return True
        answer = QMessageBox.question(
            self,
            "저장하지 않은 변경사항",
            "자막 변경사항을 저장하시겠습니까?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            return self.save()
        return answer == QMessageBox.StandardButton.No

    def navigate(self, destination: int) -> None:
        count = len(self.document.cards)
        if not count:
            return
        self.preview_index = max(0, min(destination, count - 1))
        self.card_list.setCurrentRow(self.preview_index)
        self._emit_preview()

    def set_preview_position(self, destination: int) -> None:
        """Synchronize the card selection without emitting another Preview request."""
        count = len(self.document.cards)
        if not 0 <= destination < count:
            return
        self.preview_index = destination
        self.card_list.blockSignals(True)
        self.card_list.setCurrentRow(destination)
        self.card_list.blockSignals(False)
        self._populate_source_group()
        self._refresh_labels()

    def move_preview(self, offset: int) -> None:
        self.navigate(self.preview_index + offset)

    def mark_live(self) -> None:
        self.live_index = self.preview_index
        self._refresh_labels()

    def set_group_size(self, value: int) -> None:
        self.document.set_group_size(value)
        self.live_index = -1
        count = len(self.document.cards)
        self.preview_index = min(max(self.preview_index, 0), count - 1) if count else -1
        self._refresh()
        if self.preview_index >= 0:
            self._emit_preview()
        self.document_changed.emit(self.document)

    def _card_selected(self, index: int) -> None:
        if index < 0 or index >= len(self.document.cards):
            return
        self.preview_index = index
        self._populate_source_group()
        self._refresh_labels()
        self._emit_preview()

    def _populate_source_group(self) -> None:
        self.line_list.clear()
        if self.preview_index < 0:
            return
        start = self.preview_index * self.document.group_size
        end = min(start + self.document.group_size, len(self.document.lines))
        for source_index in range(start, end):
            line = self.document.lines[source_index]
            label = line if line else "(빈 자막)"
            item = QListWidgetItem(f"{source_index + 1}. {label}")
            item.setData(Qt.ItemDataRole.UserRole, source_index)
            self.line_list.addItem(item)

    def _source_selected(self, row: int) -> None:
        item = self.line_list.item(row)
        if item is None:
            self._selected_source_index = -1
            self.line_edit.clear()
            return
        self._selected_source_index = int(item.data(Qt.ItemDataRole.UserRole))
        self.line_edit.setText(self.document.lines[self._selected_source_index])

    def _commit_line_edit(self) -> None:
        if self._selected_source_index < 0:
            return
        try:
            self.document.edit_line(self._selected_source_index, self.line_edit.text())
        except ValueError as error:
            QMessageBox.warning(self, "원본 줄", str(error))
            return
        self.live_index = -1
        self._refresh()
        self.document_changed.emit(self.document)

    def _add_line(self) -> None:
        index = (
            self._selected_source_index
            if self._selected_source_index >= 0
            else len(self.document.lines)
        )
        self.document.add_line("새 자막", index)
        self.live_index = -1
        self.preview_index = index // self.document.group_size
        self._selected_source_index = index
        self._refresh()
        self._select_source_index(index)
        self.line_edit.setFocus()
        self.line_edit.selectAll()
        self.document_changed.emit(self.document)

    def _select_source_index(self, source_index: int) -> None:
        for row in range(self.line_list.count()):
            item = self.line_list.item(row)
            if int(item.data(Qt.ItemDataRole.UserRole)) == source_index:
                self.line_list.setCurrentRow(row)
                return

    def _delete_line(self) -> None:
        if self._selected_source_index < 0:
            return
        self.document.delete_line(self._selected_source_index)
        self.live_index = -1
        count = len(self.document.cards)
        self.preview_index = min(self.preview_index, count - 1)
        self._selected_source_index = -1
        self._refresh()
        self.document_changed.emit(self.document)
        if self.preview_index >= 0:
            self._emit_preview()

    def _move_line(self, offset: int) -> None:
        if self._selected_source_index < 0:
            return
        destination = self.document.move_line(
            self._selected_source_index,
            self._selected_source_index + offset,
        )
        self.live_index = -1
        self.preview_index = destination // self.document.group_size
        self._refresh()
        self.document_changed.emit(self.document)

    def _refresh(self) -> None:
        current = self.preview_index
        self.card_list.blockSignals(True)
        self.card_list.clear()
        for index, card in enumerate(self.document.cards):
            label = self._card_label(card)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setSizeHint(
                item.sizeHint().expandedTo(self.card_list.fontMetrics().size(0, label))
            )
            self.card_list.addItem(item)
        self.card_list.setCurrentRow(current)
        self.card_list.blockSignals(False)
        self._populate_source_group()
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        selected_card_live = (
            self.live_index >= 0 and self.live_index == self.preview_index
        )
        if self.card_list.property("selectedCardLive") != selected_card_live:
            self.card_list.setProperty("selectedCardLive", selected_card_live)
            style = self.card_list.style()
            style.unpolish(self.card_list)
            style.polish(self.card_list)
        for index in range(self.card_list.count()):
            item = self.card_list.item(index)
            labels: list[str] = []
            if index == self.live_index:
                labels.append("LIVE")
            if index == self.preview_index:
                labels.append("PREVIEW")
            card = self.document.cards[index]
            prefix = f"[{' + '.join(labels)}]  " if labels else ""
            item.setText(prefix + self._card_label(card))
            if index == self.live_index:
                item.setBackground(self._card_live_background)
                item.setForeground(self._card_active_text)
            elif index == self.preview_index:
                item.setBackground(self._card_preview_background)
                item.setForeground(self._card_active_text)
            else:
                item.setBackground(Qt.GlobalColor.transparent)
                item.setForeground(self._card_text)
        modified = " ● 수정됨" if self.document.is_modified else ""
        source = str(self.document.path) if self.document.path else "자막 파일 없음"
        self.file_label.setText(source + modified)
        self.save_button.setEnabled(bool(self.document.lines))

    @staticmethod
    def _card_label(card: str) -> str:
        return card if card.strip() else "(빈 자막)"

    def _emit_preview(self) -> None:
        cards = self.document.cards
        if not 0 <= self.preview_index < len(cards):
            return
        self.preview_requested.emit(
            Content.subtitle(
                cards[self.preview_index],
                self.preview_index,
                self.subtitle_style,
                self.key_color,
            )
        )
