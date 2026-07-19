from __future__ import annotations

from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget

from church_presenter.domain.enums import ChannelRole
from church_presenter.domain.models import Content
from church_presenter.rendering.output_surface import AspectRatioContainer, OutputSurface
from church_presenter.services.pdf_service import PdfRenderCoordinator
from church_presenter.ui.labels import channel_label


class SimulationWindow(QMainWindow):
    """Resizable virtual output backed by the production rendering surface."""

    def __init__(
        self,
        role: ChannelRole,
        coordinator: PdfRenderCoordinator,
        profile: tuple[int, int],
        device_pixel_ratio: float,
    ) -> None:
        super().__init__()
        self.role = role
        self.surface = OutputSurface(coordinator, render_scale=device_pixel_ratio)
        self.profile = profile
        self.device_pixel_ratio = device_pixel_ratio
        self.setWindowTitle(f"{channel_label(role)} 출력 시뮬레이터")
        root = QWidget()
        layout = QVBoxLayout(root)
        label = QLabel(f"Virtual {profile[0]}x{profile[1]} · DPR {device_pixel_ratio:.2f} · LIVE")
        label.setProperty("role", "danger")
        layout.addWidget(label)
        layout.addWidget(AspectRatioContainer(self.surface), 1)
        self.setCentralWidget(root)
        self.resize(720, 450)

    def set_content(self, content: Content, fade_duration_ms: int = 0) -> None:
        self.surface.set_content(content, fade_duration_ms)

    def safe_close(self) -> None:
        self.set_content(Content.black())
        self.repaint()
        self.close()
