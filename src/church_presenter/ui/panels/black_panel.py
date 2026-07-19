from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

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
        row = QHBoxLayout()
        preview_broadcast = QPushButton("Broadcast Preview → BLACK")
        preview_venue = QPushButton("Venue Preview → BLACK")
        send_both = QPushButton("Send to Both")
        take_broadcast = QPushButton("TAKE Broadcast")
        take_venue = QPushButton("TAKE Venue")
        take_both = QPushButton("TAKE BOTH")
        take_both.setStyleSheet("font-weight:700;background:#dc2626;color:white;padding:10px;")
        for widget in (
            preview_broadcast,
            preview_venue,
            send_both,
            take_broadcast,
            take_venue,
            take_both,
        ):
            row.addWidget(widget)
        layout.addLayout(row)
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
