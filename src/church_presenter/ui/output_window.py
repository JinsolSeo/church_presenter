from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QScreen
from PySide6.QtWidgets import QMainWindow

from church_presenter.domain.enums import ChannelRole
from church_presenter.domain.models import Content
from church_presenter.rendering.output_surface import OutputSurface
from church_presenter.services.pdf_service import PdfRenderCoordinator


class OutputWindow(QMainWindow):
    """Borderless physical output window for one assigned screen."""

    def __init__(
        self,
        role: ChannelRole,
        coordinator: PdfRenderCoordinator,
    ) -> None:
        super().__init__()
        self.role = role
        self.surface = OutputSurface(coordinator)
        self.setCentralWidget(self.surface)
        self.setWindowTitle(f"{role.value.title()} Output")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setCursor(Qt.CursorShape.BlankCursor)

    def start_on_screen(self, screen: QScreen) -> None:
        self.windowHandle().setScreen(screen)
        self.setGeometry(screen.geometry())
        self.showFullScreen()

    def set_content(self, content: Content, fade_duration_ms: int = 0) -> None:
        self.surface.set_content(content, fade_duration_ms)

    def safe_close(self) -> None:
        self.set_content(Content.black())
        self.repaint()
        self.close()


class BroadcastOutputWindow(OutputWindow):
    def __init__(self, coordinator: PdfRenderCoordinator) -> None:
        super().__init__(ChannelRole.BROADCAST, coordinator)


class VenueOutputWindow(OutputWindow):
    def __init__(self, coordinator: PdfRenderCoordinator) -> None:
        super().__init__(ChannelRole.VENUE, coordinator)
