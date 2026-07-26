from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QVideoFrame, QVideoFrameFormat
from PySide6.QtWidgets import QApplication

from church_presenter.domain.models import Content, SubtitleStyle
from church_presenter.rendering.output_surface import OutputSurface
from church_presenter.services.pdf_service import PdfRenderCoordinator
from church_presenter.ui.output_window import BroadcastOutputWindow


def test_output_window_covers_assigned_screen_without_native_fullscreen(qtbot) -> None:
    application = QApplication.instance()
    assert isinstance(application, QApplication)
    screen = application.primaryScreen()
    assert screen is not None

    window = BroadcastOutputWindow(PdfRenderCoordinator())
    qtbot.addWidget(window)

    window.start_on_screen(screen)

    assert window.windowTitle() == "송출 출력"
    handle = window.windowHandle()
    assert handle is not None
    assert handle.screen() is screen
    assert window.geometry() == screen.geometry()
    assert window.isVisible()
    assert not window.isFullScreen()
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert window.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus

    content = Content.subtitle("Live output", 0, SubtitleStyle(), "#00FF00")
    window.set_content(content)
    assert window.surface.target_content == content


def test_output_surface_uses_native_video_frame_until_content_changes(
    qtbot,
    tmp_path: Path,
) -> None:
    path = tmp_path / "native-frame.mp4"
    path.write_bytes(b"test")
    surface = OutputSurface(PdfRenderCoordinator())
    qtbot.addWidget(surface)
    surface.resize(320, 180)
    surface.show()
    surface.set_content(Content.video(path))

    preview = QImage(320, 180, QImage.Format.Format_RGB32)
    preview.fill(Qt.GlobalColor.blue)
    surface.set_video_frame(str(path.resolve()), preview)
    assert not surface.video_widget.isVisible()

    frame = QVideoFrame(
        QVideoFrameFormat(
            QSize(320, 180),
            QVideoFrameFormat.PixelFormat.Format_RGBA8888,
        )
    )
    assert frame.isValid()
    surface.set_video_frame(str(path.resolve()), frame)

    assert surface.video_widget.isVisible()
    assert surface.video_widget.videoSink().videoFrame().isValid()

    surface.set_content(Content.black())
    assert not surface.video_widget.isVisible()
    assert not surface.video_widget.videoSink().videoFrame().isValid()
