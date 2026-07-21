from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from church_presenter.domain.enums import ChannelRole, ContentType
from church_presenter.domain.models import Content


class BlackPanel(QWidget):
    """Prepare safe black or chroma-color blank screens for Preview and Live."""

    COLOR_PRESETS = (
        ("검정", "#000000"),
        ("크로마키 그린", "#00FF00"),
        ("크로마키 블루", "#0000FF"),
    )

    preview_requested = Signal(str, object)
    send_to_both_requested = Signal(object)
    take_requested = Signal(str)
    take_both_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._selected_color = "#000000"
        layout = QHBoxLayout(self)
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        explanation = QLabel(
            "오른쪽에서 빈 화면 색상을 고른 뒤 Preview에 준비하고 TAKE 하십시오. "
            "Send to Both는 두 Preview에만 복사합니다."
        )
        explanation.setWordWrap(True)
        controls_layout.addWidget(explanation)
        actions = QGridLayout()
        self.preview_broadcast_button = QPushButton("송출 Preview 준비")
        self.preview_venue_button = QPushButton("현장 Preview 준비")
        self.send_both_button = QPushButton("Send to Both")
        self.take_broadcast_button = QPushButton("TAKE 송출")
        self.take_venue_button = QPushButton("TAKE 현장")
        self.take_both_button = QPushButton("TAKE BOTH")
        self.send_both_button.setProperty("variant", "primary")
        for take_button in (
            self.take_broadcast_button,
            self.take_venue_button,
            self.take_both_button,
        ):
            take_button.setProperty("variant", "take")
        actions.addWidget(self.preview_broadcast_button, 0, 0)
        actions.addWidget(self.preview_venue_button, 0, 1)
        actions.addWidget(self.send_both_button, 0, 2)
        actions.addWidget(self.take_broadcast_button, 1, 0)
        actions.addWidget(self.take_venue_button, 1, 1)
        actions.addWidget(self.take_both_button, 1, 2)
        controls_layout.addLayout(actions)
        controls_layout.addStretch()
        layout.addWidget(controls, 1)

        self.preset_panel = QFrame()
        self.preset_panel.setObjectName("BlankPresetPanel")
        self.preset_panel.setMaximumWidth(240)
        preset_layout = QVBoxLayout(self.preset_panel)
        preset_layout.addWidget(QLabel("빈 화면 프리셋"))
        self.selected_label = QLabel()
        self.selected_label.setProperty("role", "secondary")
        preset_layout.addWidget(self.selected_label)
        self.preset_buttons: dict[str, QPushButton] = {}
        for name, color in self.COLOR_PRESETS:
            button = QPushButton(name)
            button.setCheckable(True)
            button.setIcon(self._color_icon(color))
            button.clicked.connect(
                lambda _checked=False, selected=color: self.select_preset(selected)
            )
            self.preset_buttons[color] = button
            preset_layout.addWidget(button)
        preset_layout.addStretch()
        layout.addWidget(self.preset_panel)
        self.select_preset("#000000")

        self.preview_broadcast_button.clicked.connect(
            lambda: self.preview_requested.emit(
                ChannelRole.BROADCAST.value,
                self.selected_content,
            )
        )
        self.preview_venue_button.clicked.connect(
            lambda: self.preview_requested.emit(
                ChannelRole.VENUE.value,
                self.selected_content,
            )
        )
        self.send_both_button.clicked.connect(
            lambda: self.send_to_both_requested.emit(self.selected_content)
        )
        self.take_broadcast_button.clicked.connect(
            lambda: self.take_requested.emit(ChannelRole.BROADCAST.value)
        )
        self.take_venue_button.clicked.connect(
            lambda: self.take_requested.emit(ChannelRole.VENUE.value)
        )
        self.take_both_button.clicked.connect(self.take_both_requested)

    @property
    def selected_content(self) -> Content:
        """Return an immutable snapshot for the currently selected preset."""
        return Content.solid_color(self._selected_color)

    def select_preset(self, color: str) -> None:
        """Select a preset without changing either Preview or Live output."""
        content = Content.solid_color(color)
        self._selected_color = (
            "#000000" if content.kind is ContentType.BLACK else content.background_color
        )
        for preset_color, button in self.preset_buttons.items():
            button.setChecked(preset_color == self._selected_color)
        name = next(
            preset_name
            for preset_name, preset_color in self.COLOR_PRESETS
            if preset_color == self._selected_color
        )
        self.selected_label.setText(f"선택 · {name} · {self._selected_color}")

    @staticmethod
    def _color_icon(color: str) -> QIcon:
        swatch = QPixmap(18, 18)
        swatch.fill(QColor(color))
        return QIcon(swatch)
