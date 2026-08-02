from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class TilePickerDialog(QDialog):
    """Compact grid picker for long book, chapter, and verse lists."""

    def __init__(
        self,
        title: str,
        items: list[tuple[str, Any]],
        current_index: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.selected_index = current_index
        self.column_count = 6 if any(len(label) > 3 for label, _data in items) else 10
        self.resize(720, 560)

        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"{title}을(를) 선택하세요."))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        grid = QGridLayout(host)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        for index, (label, _data) in enumerate(items):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setChecked(index == current_index)
            button.setMinimumHeight(36)
            button.clicked.connect(lambda _checked=False, value=index: self._choose(value))
            grid.addWidget(button, index // self.column_count, index % self.column_count)
        scroll.setWidget(host)
        root.addWidget(scroll)

    def _choose(self, index: int) -> None:
        self.selected_index = index
        self.accept()


class TilePickerButton(QPushButton):
    """QComboBox-like button that opens its values in a tile dialog."""

    currentIndexChanged = Signal(int)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.picker_title = title
        self._items: list[tuple[str, Any]] = []
        self._current_index = -1
        self.setText("선택 ▾")
        self.clicked.connect(self.open_picker)

    def clear(self) -> None:
        changed = self._current_index != -1
        self._items.clear()
        self._current_index = -1
        self.setText("선택 ▾")
        if changed:
            self.currentIndexChanged.emit(-1)

    def addItem(self, label: str, data: Any = None) -> None:
        self._items.append((label, data))
        if self._current_index < 0:
            self.setCurrentIndex(0)

    def count(self) -> int:
        return len(self._items)

    def currentIndex(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        target = index if 0 <= index < len(self._items) else -1
        if target == self._current_index:
            return
        self._current_index = target
        self.setText(f"{self._items[target][0]} ▾" if target >= 0 else "선택 ▾")
        self.currentIndexChanged.emit(target)

    def currentData(self) -> Any:
        return self._items[self._current_index][1] if self._current_index >= 0 else None

    def currentText(self) -> str:
        return self._items[self._current_index][0] if self._current_index >= 0 else ""

    def findData(self, data: Any) -> int:
        return next(
            (index for index, (_label, value) in enumerate(self._items) if value == data),
            -1,
        )

    def open_picker(self) -> None:
        if not self._items:
            return
        dialog = TilePickerDialog(
            self.picker_title,
            self._items,
            self._current_index,
            self,
        )
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        selected_index = dialog.selected_index
        dialog.deleteLater()
        if accepted:
            self.setCurrentIndex(selected_index)
