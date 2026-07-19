from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QPushButton, QWidget


class ColorButton(QPushButton):
    """Compact color picker storing a validated #RRGGBB value."""

    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self.clicked.connect(self._choose)
        self._refresh()

    @property
    def color(self) -> str:
        return self._color.name().upper()

    def set_color(self, color: str) -> None:
        candidate = QColor(color)
        if candidate.isValid():
            self._color = candidate
            self._refresh()

    def _choose(self) -> None:
        selected = QColorDialog.getColor(self._color, self, "색상 선택")
        if selected.isValid():
            self._color = selected
            self._refresh()
            self.setProperty("changed", True)

    def _refresh(self) -> None:
        foreground = "#111827" if self._color.lightness() > 145 else "#FFFFFF"
        self.setText(self.color)
        self.setStyleSheet(
            f"background-color:{self.color};color:{foreground};font-weight:700;"
        )
