from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from church_presenter.services.subtitle_merge_service import (
    padding_count,
    read_subtitle_lines,
    save_merged_subtitle,
)

LINE_COUNT_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class SubtitleMergeDialog(QDialog):
    """Select, order, pad, and save a weekly merged subtitle TXT file."""

    def __init__(
        self,
        initial_folder: Path | None,
        group_size: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("자막 합치기")
        self.resize(820, 560)
        self.folder = initial_folder
        self.result_path: Path | None = None

        root = QVBoxLayout(self)
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("가사 폴더"))
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        folder_button = QPushButton("폴더 선택")
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(folder_button)
        root.addLayout(folder_row)

        lists_row = QHBoxLayout()
        available_host = QWidget()
        available_layout = QVBoxLayout(available_host)
        available_layout.addWidget(QLabel("사용 가능한 TXT"))
        self.available_list = QListWidget()
        self.available_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        available_layout.addWidget(self.available_list)
        lists_row.addWidget(available_host, 1)

        transfer_host = QWidget()
        transfer_layout = QVBoxLayout(transfer_host)
        transfer_layout.addStretch()
        self.add_button = QPushButton("추가 →")
        self.remove_button = QPushButton("← 제거")
        transfer_layout.addWidget(self.add_button)
        transfer_layout.addWidget(self.remove_button)
        transfer_layout.addStretch()
        lists_row.addWidget(transfer_host)

        selected_host = QWidget()
        selected_layout = QVBoxLayout(selected_host)
        selected_layout.addWidget(QLabel("이번 주 콘티"))
        self.selected_list = QListWidget()
        selected_layout.addWidget(self.selected_list)
        order_row = QHBoxLayout()
        self.move_up_button = QPushButton("위로")
        self.move_down_button = QPushButton("아래로")
        order_row.addWidget(self.move_up_button)
        order_row.addWidget(self.move_down_button)
        selected_layout.addLayout(order_row)
        lists_row.addWidget(selected_host, 1)
        root.addLayout(lists_row, 1)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("한 번에 표시할 자막 수"))
        self.group_spin = QSpinBox()
        self.group_spin.setRange(1, 8)
        self.group_spin.setValue(group_size)
        settings_row.addWidget(self.group_spin)
        settings_row.addStretch()
        self.summary_label = QLabel()
        settings_row.addWidget(self.summary_label)
        root.addLayout(settings_row)

        explanation = QLabel(
            "각 파일의 자막 수를 기준으로 다음 파일이 새 카드에서 시작하도록 "
            "필요한 빈 자막을 자동으로 추가합니다."
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.save_button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText("합쳐서 저장")
        self.save_button.setProperty("variant", "primary")
        root.addWidget(self.buttons)

        folder_button.clicked.connect(self._choose_folder)
        self.add_button.clicked.connect(self._add_selected)
        self.remove_button.clicked.connect(self._remove_selected)
        self.move_up_button.clicked.connect(lambda: self._move_selected(-1))
        self.move_down_button.clicked.connect(lambda: self._move_selected(1))
        self.available_list.itemDoubleClicked.connect(lambda _item: self._add_selected())
        self.selected_list.itemDoubleClicked.connect(lambda _item: self._remove_selected())
        self.group_spin.valueChanged.connect(self._refresh_selected_labels)
        self.selected_list.currentRowChanged.connect(self._refresh_actions)
        self.buttons.rejected.connect(self.reject)
        self.save_button.clicked.connect(self._save)

        if self.folder and self.folder.is_dir():
            self._load_folder(self.folder)
        else:
            self.folder = None
        self._refresh_actions()

    def _choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "가사 TXT 폴더 선택",
            str(self.folder or Path.home()),
        )
        if selected:
            self._load_folder(Path(selected))

    def _load_folder(self, folder: Path) -> None:
        self.folder = folder.expanduser().resolve()
        self.folder_edit.setText(str(self.folder))
        self.folder_edit.setToolTip(str(self.folder))
        self.available_list.clear()
        self.selected_list.clear()

        failures: list[str] = []
        paths = sorted(
            (
                path
                for path in self.folder.iterdir()
                if path.is_file() and path.suffix.casefold() == ".txt"
            ),
            key=lambda path: path.name.casefold(),
        )
        for path in paths:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            try:
                line_count = len(read_subtitle_lines(path))
            except (OSError, UnicodeError):
                item.setText(f"{path.name}\n읽기 오류")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                failures.append(path.name)
            else:
                item.setText(f"{path.name}\n자막 {line_count}개")
                item.setData(LINE_COUNT_ROLE, line_count)
            self.available_list.addItem(item)

        self._refresh_actions()
        if failures:
            QMessageBox.warning(
                self,
                "일부 자막 파일을 읽을 수 없음",
                "UTF-8 TXT 파일인지 확인하십시오.\n\n" + "\n".join(failures),
            )

    def _selected_paths(self) -> list[Path]:
        return [
            Path(str(self.selected_list.item(row).data(Qt.ItemDataRole.UserRole)))
            for row in range(self.selected_list.count())
        ]

    def _add_selected(self) -> None:
        existing = {str(path) for path in self._selected_paths()}
        added_row = -1
        for source in self.available_list.selectedItems():
            path = str(source.data(Qt.ItemDataRole.UserRole))
            if path in existing or source.data(LINE_COUNT_ROLE) is None:
                continue
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setData(LINE_COUNT_ROLE, int(source.data(LINE_COUNT_ROLE)))
            self.selected_list.addItem(item)
            existing.add(path)
            added_row = self.selected_list.count() - 1
        if added_row >= 0:
            self.selected_list.setCurrentRow(added_row)
        self._refresh_selected_labels()

    def _remove_selected(self) -> None:
        row = self.selected_list.currentRow()
        if row >= 0:
            self.selected_list.takeItem(row)
            self.selected_list.setCurrentRow(
                min(row, self.selected_list.count() - 1)
            )
        self._refresh_selected_labels()

    def _move_selected(self, offset: int) -> None:
        row = self.selected_list.currentRow()
        destination = row + offset
        if row < 0 or not 0 <= destination < self.selected_list.count():
            return
        item = self.selected_list.takeItem(row)
        self.selected_list.insertItem(destination, item)
        self.selected_list.setCurrentRow(destination)
        self._refresh_selected_labels()

    def _refresh_selected_labels(self) -> None:
        group_size = self.group_spin.value()
        total_padding = 0
        count = self.selected_list.count()
        for row in range(count):
            item = self.selected_list.item(row)
            path = Path(str(item.data(Qt.ItemDataRole.UserRole)))
            line_count = int(item.data(LINE_COUNT_ROLE))
            padding = padding_count(line_count, group_size) if row < count - 1 else 0
            total_padding += padding
            item.setText(
                f"{row + 1}. {path.name}\n"
                f"자막 {line_count}개 · 빈 자막 {padding}개 자동 추가"
            )
        self.summary_label.setText(
            f"파일 {count}개 · 빈 자막 총 {total_padding}개"
        )
        self._refresh_actions()

    def _refresh_actions(self) -> None:
        row = self.selected_list.currentRow()
        count = self.selected_list.count()
        self.remove_button.setEnabled(row >= 0)
        self.move_up_button.setEnabled(row > 0)
        self.move_down_button.setEnabled(0 <= row < count - 1)
        self.save_button.setEnabled(count > 0 and self.folder is not None)

    def _save(self) -> None:
        paths = self._selected_paths()
        if not paths:
            QMessageBox.warning(self, "자막 합치기", "합칠 자막 파일을 선택하십시오.")
            return
        suggested = (self.folder or Path.home()) / "merged_subtitles.txt"
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "합친 자막 저장",
            str(suggested),
            "Text files (*.txt)",
        )
        if not selected:
            return
        destination = Path(selected)
        if not destination.suffix:
            destination = destination.with_suffix(".txt")
        try:
            self.result_path = save_merged_subtitle(
                paths,
                destination,
                self.group_spin.value(),
            )
        except (OSError, UnicodeError, ValueError) as error:
            QMessageBox.critical(self, "자막 저장 실패", str(error))
            return
        QMessageBox.information(
            self,
            "자막 합치기",
            f"합친 자막을 저장했습니다.\n{self.result_path}",
        )
        self.accept()
