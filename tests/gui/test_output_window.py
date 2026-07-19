from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from church_presenter.domain.models import Content, SubtitleStyle
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
