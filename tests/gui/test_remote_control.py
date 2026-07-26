from __future__ import annotations

import inspect
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtWidgets import QLineEdit, QPushButton, QVBoxLayout, QWidget

from church_presenter.domain.models import Content
from church_presenter.remote.frame_capture import MAX_FRAME_WIDTH, FrameCaptureService
from church_presenter.remote.input_dispatcher import RemoteInputDispatcher
from church_presenter.remote.network_service import RemoteNetworkService
from church_presenter.remote.protocol import KeyCommand, PointerCommand
from church_presenter.rendering.output_surface import OutputSurface
from church_presenter.services.pdf_service import PdfRenderCoordinator
from church_presenter.ui.dialogs.remote_connection_dialog import (
    RemoteConnectionDialog,
    qr_pixmap,
)


def test_remote_pointer_and_text_follow_normal_qt_event_flow(qtbot) -> None:
    root = QWidget()
    root.resize(400, 200)
    layout = QVBoxLayout(root)
    button = QPushButton("Remote")
    editor = QLineEdit()
    layout.addWidget(button)
    layout.addWidget(editor)
    qtbot.addWidget(root)
    root.show()
    clicked: list[bool] = []
    button.clicked.connect(lambda: clicked.append(True))
    dispatcher = RemoteInputDispatcher(lambda: root)

    button_center = button.mapTo(root, button.rect().center())
    x = button_center.x() / (root.width() - 1)
    y = button_center.y() / (root.height() - 1)
    dispatcher.dispatch(PointerCommand("press", x, y, "left"))
    dispatcher.dispatch(PointerCommand("release", x, y, "left"))
    assert clicked == [True]

    editor.setFocus()
    root.activateWindow()
    qtbot.wait(10)
    dispatcher.dispatch(KeyCommand("press", "a", "KeyA", "a"))
    dispatcher.dispatch(KeyCommand("release", "a", "KeyA", "a"))
    assert editor.text() == "a"


def test_capture_stops_without_clients_and_qr_is_rendered(qapp, qtbot) -> None:
    root = QWidget()
    root.resize(320, 180)
    qtbot.addWidget(root)
    root.show()
    capture = FrameCaptureService(qapp, root)

    assert not capture.timer.isActive()
    capture.set_client_count(1)
    assert capture.timer.isActive()
    capture.set_client_count(0)
    assert not capture.timer.isActive()
    assert not qr_pixmap("http://192.168.0.2:8765/connect?token=test").isNull()


def test_remote_capture_is_capped_for_mobile_decode(qapp, qtbot) -> None:
    root = QWidget()
    root.resize(MAX_FRAME_WIDTH + 320, 900)
    qtbot.addWidget(root)
    root.show()
    capture = FrameCaptureService(qapp, root)
    frames: list[tuple[bytes, dict[str, object]]] = []
    capture.frame_ready.connect(
        lambda jpeg, metadata: frames.append((jpeg, metadata))
    )

    capture.set_client_count(1)
    qtbot.waitUntil(lambda: bool(frames), timeout=3000)
    capture.set_client_count(0)

    jpeg, metadata = frames[-1]
    assert jpeg.startswith(b"\xff\xd8")
    assert metadata["width"] == MAX_FRAME_WIDTH
    assert int(metadata["height"]) < root.height()


def test_remote_dialog_is_non_modal_and_reports_multiple_clients(qtbot) -> None:
    service = RemoteNetworkService()
    dialog = RemoteConnectionDialog(service)
    qtbot.addWidget(dialog)
    url = "http://192.168.0.2:8765/connect?token=test"

    service.server_started.emit("192.168.0.2", 8765, url)
    service.state_changed.emit("waiting", "")
    service.client_count_changed.emit(2)

    assert not dialog.isModal()
    assert dialog.windowModality() is Qt.WindowModality.NonModal
    assert dialog.url_label.text() == url
    assert dialog.status_label.text() == "2대 연결됨"
    assert dialog.clients_label.text() == "2대"
    assert dialog.copy_button.isEnabled()
    assert "같은 Wi-Fi" in dialog.notice.text()


def test_native_video_frame_is_composited_into_controller_capture(qtbot) -> None:
    root = QWidget()
    root.resize(320, 180)
    surface = OutputSurface(PdfRenderCoordinator(), root)
    surface.setGeometry(0, 0, 320, 180)
    path = Path("native.mp4")
    surface.content = Content.video(path)
    frame_image = QImage(QSize(320, 180), QImage.Format.Format_RGB32)
    frame_image.fill(Qt.GlobalColor.red)
    surface.video_native_frame = QVideoFrame(frame_image)
    cue_image = QImage(QSize(320, 180), QImage.Format.Format_RGB32)
    cue_image.fill(Qt.GlobalColor.blue)
    surface.video_frame = cue_image
    qtbot.addWidget(root)
    root.show()

    captured = QImage(QSize(320, 180), QImage.Format.Format_RGB32)
    captured.fill(Qt.GlobalColor.black)
    FrameCaptureService._composite_native_video(root, captured)

    assert captured.pixelColor(QPoint(160, 90)) == Qt.GlobalColor.blue
    implementation = inspect.getsource(FrameCaptureService._composite_native_video)
    assert "video_native_frame.toImage" not in implementation
    assert "surface.video_frame" in implementation


def test_remote_server_module_has_no_qt_widget_dependency() -> None:
    from church_presenter.remote import server

    source = server.Path(server.__file__).read_text(encoding="utf-8")
    assert "QtWidgets" not in source
    assert "QWidget" not in source
