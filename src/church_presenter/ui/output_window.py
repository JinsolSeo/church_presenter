from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QScreen
from PySide6.QtWidgets import QMainWindow

from church_presenter.domain.enums import ChannelRole
from church_presenter.domain.models import Content
from church_presenter.rendering.output_surface import OutputSurface
from church_presenter.services.pdf_service import PdfRenderCoordinator
from church_presenter.ui.labels import channel_label


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
        self.setWindowTitle(f"{channel_label(role)} 출력")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setCursor(Qt.CursorShape.BlankCursor)

    def start_on_screen(self, screen: QScreen) -> None:
        # Native fullscreen puts the whole application into a dedicated Space
        # on macOS. A borderless screen-sized window keeps the Controller and
        # both physical outputs visible at the same time on every platform.
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self.surface.update()

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
