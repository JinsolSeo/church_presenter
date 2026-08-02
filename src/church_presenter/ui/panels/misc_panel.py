from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from church_presenter.ui.panels.black_panel import BlackPanel
from church_presenter.ui.panels.instant_panel import InstantPanel


class MiscPanel(QWidget):
    """Lay out instant text and blank-screen tools as equal secondary sections."""

    def __init__(
        self,
        instant_panel: InstantPanel,
        black_panel: BlackPanel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.instant_panel = instant_panel
        self.black_panel = black_panel

        layout = QHBoxLayout(self)
        self.instant_section = self._section("즉석 문구", instant_panel)
        self.blank_section = self._section("빈 화면", black_panel)
        layout.addWidget(self.instant_section, 1)
        layout.addWidget(self.blank_section, 1)

    @staticmethod
    def _section(title: str, panel: QWidget) -> QFrame:
        section = QFrame()
        section.setObjectName("MiscSection")
        section.setFrameShape(QFrame.Shape.StyledPanel)
        section_layout = QVBoxLayout(section)
        heading = QLabel(title)
        heading.setProperty("role", "sectionTitle")
        section_layout.addWidget(heading)
        section_layout.addWidget(panel, 1)
        return section
