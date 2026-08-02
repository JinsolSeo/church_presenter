from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from church_presenter.domain.models import Content, SubtitleStyle


class InstantPanel(QWidget):
    """Prepare and navigate unplanned text without a secondary mode selector."""

    preview_requested = Signal(object)
    take_requested = Signal()
    style_requested = Signal(str)
    status_changed = Signal(str)

    def __init__(
        self,
        text_style: SubtitleStyle,
        text_key: str,
        group_size: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.text_style = text_style
        self.text_key = text_key
        self.group_size = max(1, group_size)
        self.preview_index = 0
        self.live_source = ""

        layout = QVBoxLayout(self)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "즉석으로 송출할 문구를 입력하세요. 여러 줄은 스타일의 표시 개수대로 묶입니다."
        )
        layout.addWidget(self.text_edit, 1)

        controls = QHBoxLayout()
        self.style_button = QPushButton("Style")
        self.previous_button = QPushButton("◀ 이전")
        self.next_button = QPushButton("다음 ▶")
        self.take_button = QPushButton("TAKE")
        self.take_button.setProperty("variant", "take")
        controls.addWidget(self.style_button)
        controls.addStretch()
        navigation_host = QWidget()
        navigation = QHBoxLayout(navigation_host)
        navigation.setContentsMargins(0, 0, 0, 0)
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.next_button)
        navigation.addWidget(self.take_button)
        controls.addWidget(navigation_host)
        controls.addStretch()
        balance = QWidget()
        balance.setFixedWidth(self.style_button.sizeHint().width())
        controls.addWidget(balance)
        layout.addLayout(controls)

        self.style_button.clicked.connect(lambda: self.style_requested.emit("instant_text"))
        self.previous_button.clicked.connect(lambda: self.move_preview(-1))
        self.next_button.clicked.connect(lambda: self.move_preview(1))
        self.take_button.clicked.connect(self.take_requested)
        self.text_edit.textChanged.connect(self._text_changed)

    @property
    def output_count(self) -> int:
        return len(self._cards())

    def set_style(self, style: SubtitleStyle, key_color: str) -> None:
        self.text_style = style
        self.text_key = key_color

    def set_group_size(self, value: int) -> None:
        if value < 1:
            raise ValueError("instant text group size must be at least one")
        if value != self.group_size:
            self.group_size = value
            self.preview_index = min(self.preview_index, max(0, self.output_count - 1))

    def _lines(self) -> list[str]:
        return [line.strip() for line in self.text_edit.toPlainText().splitlines() if line.strip()]

    def _cards(self) -> list[str]:
        lines = self._lines()
        return [
            "\n".join(lines[start : start + self.group_size])
            for start in range(0, len(lines), self.group_size)
        ]

    def _text_changed(self) -> None:
        self.preview_index = min(self.preview_index, max(0, self.output_count - 1))

    def navigate(self, destination: int) -> None:
        if not self.output_count:
            return
        self.preview_index = max(0, min(destination, self.output_count - 1))
        self.preview_current()

    def move_preview(self, offset: int) -> None:
        self.navigate(self.preview_index + offset)

    def preview_current(self) -> None:
        cards = self._cards()
        if not cards:
            self.status_changed.emit("송출할 내용을 입력하십시오.")
            return
        self.preview_index = max(0, min(self.preview_index, len(cards) - 1))
        self.preview_requested.emit(
            Content.subtitle(
                cards[self.preview_index],
                self.preview_index,
                self.text_style,
                self.text_key,
                source="instant_text",
            )
        )

    def mark_live(self, source: str) -> None:
        self.live_source = source
