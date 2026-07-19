from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from church_presenter.domain.enums import ChannelRole
from church_presenter.domain.models import Content


class BlackPanel(QWidget):
    """Safe black Preview and atomic TAKE controls."""

    preview_requested = Signal(str, object)
    send_to_both_requested = Signal(object)
    take_requested = Signal(str)
    take_both_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "검은 화면을 먼저 Preview에 준비한 뒤 TAKE 하십시오. "
            "Send to Both는 두 Preview에만 복사합니다."
        )
        layout.addWidget(explanation)
        actions = QGridLayout()
        preview_broadcast = QPushButton("송출 Preview → BLACK")
        preview_venue = QPushButton("현장 Preview → BLACK")
        send_both = QPushButton("Send to Both")
        take_broadcast = QPushButton("TAKE 송출")
        take_venue = QPushButton("TAKE 현장")
        take_both = QPushButton("TAKE BOTH")
        send_both.setProperty("variant", "primary")
        for take_button in (take_broadcast, take_venue, take_both):
            take_button.setProperty("variant", "take")
        actions.addWidget(preview_broadcast, 0, 0)
        actions.addWidget(preview_venue, 0, 1)
        actions.addWidget(send_both, 0, 2)
        actions.addWidget(take_broadcast, 1, 0)
        actions.addWidget(take_venue, 1, 1)
        actions.addWidget(take_both, 1, 2)
        layout.addLayout(actions)
        layout.addStretch()
        preview_broadcast.clicked.connect(
            lambda: self.preview_requested.emit(ChannelRole.BROADCAST.value, Content.black())
        )
        preview_venue.clicked.connect(
            lambda: self.preview_requested.emit(ChannelRole.VENUE.value, Content.black())
        )
        send_both.clicked.connect(lambda: self.send_to_both_requested.emit(Content.black()))
        take_broadcast.clicked.connect(
            lambda: self.take_requested.emit(ChannelRole.BROADCAST.value)
        )
        take_venue.clicked.connect(lambda: self.take_requested.emit(ChannelRole.VENUE.value))
        take_both.clicked.connect(self.take_both_requested)
