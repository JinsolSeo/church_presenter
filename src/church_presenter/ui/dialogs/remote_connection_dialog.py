from __future__ import annotations

from typing import ClassVar

import qrcode  # type: ignore[import-untyped]
from PySide6.QtCore import QEvent, Qt, Slot
from PySide6.QtGui import QCloseEvent, QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from church_presenter.remote.network_service import RemoteNetworkService


def qr_pixmap(text: str, size: int = 280) -> QPixmap:
    """Render a QR matrix directly with Qt, without an image-processing dependency."""
    code = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=4,
    )
    code.add_data(text)
    code.make(fit=True)
    matrix = code.get_matrix()
    cells = len(matrix)
    cell_size = max(1, size // cells)
    actual_size = cells * cell_size
    image = QImage(actual_size, actual_size, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("black"))
    for row, values in enumerate(matrix):
        for column, filled in enumerate(values):
            if filled:
                painter.drawRect(
                    column * cell_size,
                    row * cell_size,
                    cell_size,
                    cell_size,
                )
    painter.end()
    return QPixmap.fromImage(image)


class RemoteConnectionDialog(QDialog):
    """Non-modal QR and lifecycle UI for the local remote server."""

    _STATE_LABELS: ClassVar[dict[str, str]] = {
        "stopped": "서버 중지됨",
        "starting": "서버 시작 중",
        "waiting": "연결 대기 중",
        "error": "서버 오류",
        "no_address": "사용 가능한 로컬 IP 없음",
    }

    def __init__(
        self,
        service: RemoteNetworkService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.setObjectName("RemoteConnectionDialog")
        self.setProperty("remoteConnectionDialog", True)
        self.setWindowTitle("원격 연결")
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumWidth(430)

        root = QVBoxLayout(self)
        title = QLabel("원격 연결")
        title.setProperty("role", "pageTitle")
        root.addWidget(title)

        address_row = QHBoxLayout()
        address_label = QLabel("접속 네트워크")
        self.address_combo = QComboBox()
        self.address_combo.setAccessibleName("원격 연결에 표시할 로컬 IP")
        address_row.addWidget(address_label)
        address_row.addWidget(self.address_combo, 1)
        root.addLayout(address_row)

        self.qr_label = QLabel("서버가 시작되면 QR 코드가 표시됩니다.")
        self.qr_label.setObjectName("RemoteQrCode")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumSize(290, 290)
        root.addWidget(self.qr_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.url_label = QLabel("")
        self.url_label.setObjectName("RemoteConnectionUrl")
        self.url_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.url_label.setWordWrap(True)
        root.addWidget(self.url_label)

        status_grid = QGridLayout()
        status_grid.addWidget(QLabel("상태"), 0, 0)
        self.status_label = QLabel("서버 중지됨")
        status_grid.addWidget(self.status_label, 0, 1)
        status_grid.addWidget(QLabel("접속 기기"), 1, 0)
        self.clients_label = QLabel("0대")
        status_grid.addWidget(self.clients_label, 1, 1)
        root.addLayout(status_grid)

        self.error_label = QLabel("")
        self.error_label.setObjectName("RemoteConnectionError")
        self.error_label.setProperty("role", "error")
        self.error_label.setWordWrap(True)
        root.addWidget(self.error_label)

        self.notice = QLabel(
            "노트북과 원격 기기가 같은 Wi-Fi에 연결되어 있어야 합니다. "
            "방화벽 또는 게스트 Wi-Fi의 기기 간 통신 차단으로 연결되지 않을 수 있습니다."
        )
        self.notice.setProperty("role", "secondary")
        self.notice.setWordWrap(True)
        root.addWidget(self.notice)

        buttons = QHBoxLayout()
        self.copy_button = QPushButton("주소 복사")
        self.copy_button.setEnabled(False)
        self.restart_button = QPushButton("서버 재시작")
        self.restart_button.setProperty("variant", "secondary")
        self.stop_button = QPushButton("연결 종료")
        self.stop_button.setProperty("variant", "danger")
        buttons.addWidget(self.copy_button)
        buttons.addStretch()
        buttons.addWidget(self.restart_button)
        buttons.addWidget(self.stop_button)
        root.addLayout(buttons)

        self.copy_button.clicked.connect(self._copy_url)
        self.restart_button.clicked.connect(self._restart)
        self.stop_button.clicked.connect(self.service.stop)
        self.service.server_started.connect(self._server_started)
        self.service.state_changed.connect(self._state_changed)
        self.service.client_count_changed.connect(self._client_count_changed)
        self.refresh_addresses()

    def refresh_addresses(self) -> None:
        selected = self.address_combo.currentData()
        self.address_combo.clear()
        for candidate in self.service.addresses():
            self.address_combo.addItem(candidate.label, candidate.address)
        index = self.address_combo.findData(selected)
        if index >= 0:
            self.address_combo.setCurrentIndex(index)

    def open_connection(self) -> None:
        self.refresh_addresses()
        self.show()
        self.raise_()
        self.activateWindow()
        if self.service.running:
            url = self.service.connection_url
            if url:
                self._server_started(
                    str(self.address_combo.currentData() or ""),
                    int(url.split(":", 2)[-1].split("/", 1)[0]),
                    url,
                )
            return
        address = self.address_combo.currentData()
        self.service.start(str(address) if isinstance(address, str) else None)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Closing the information window leaves the server running."""
        event.ignore()
        self.hide()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() is QEvent.Type.LanguageChange:
            self.setWindowTitle("원격 연결")

    @Slot(str, int, str)
    def _server_started(self, address: str, _port: int, url: str) -> None:
        index = self.address_combo.findData(address)
        if index >= 0:
            self.address_combo.setCurrentIndex(index)
        self.url_label.setText(url)
        self.qr_label.setPixmap(qr_pixmap(url))
        self.copy_button.setEnabled(True)
        self.error_label.clear()

    @Slot(str, str)
    def _state_changed(self, state: str, message: str) -> None:
        self.status_label.setText(self._STATE_LABELS.get(state, state))
        self.error_label.setText(message)
        if state in {"stopped", "error", "no_address"}:
            self.url_label.clear()
            self.qr_label.clear()
            self.qr_label.setText("서버가 시작되면 QR 코드가 표시됩니다.")
            self.copy_button.setEnabled(False)

    @Slot(int)
    def _client_count_changed(self, count: int) -> None:
        self.clients_label.setText(f"{count}대")
        if count:
            self.status_label.setText(f"{count}대 연결됨")
        elif self.service.running:
            self.status_label.setText("연결 대기 중")

    def _copy_url(self) -> None:
        clipboard = QApplication.clipboard()
        clipboard.setText(self.service.connection_url)

    def _restart(self) -> None:
        address = self.address_combo.currentData()
        self.service.restart(str(address) if isinstance(address, str) else None)
