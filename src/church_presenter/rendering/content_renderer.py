from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter

from church_presenter.domain.enums import ContentType
from church_presenter.domain.models import Content
from church_presenter.rendering.pdf_renderer import draw_contained_image
from church_presenter.rendering.subtitle_renderer import SubtitleRenderer


class ContentRenderer:
    """Shared renderer for Controller, simulation, and physical outputs."""

    def __init__(self) -> None:
        self.subtitle_renderer = SubtitleRenderer()

    def paint(
        self,
        painter: QPainter,
        bounds: QRectF,
        content: Content,
        pdf_image: QImage,
        video_frame: QImage,
    ) -> None:
        if content.kind is ContentType.SUBTITLE_KEY:
            painter.fillRect(bounds, content.key_color)
            self.subtitle_renderer.paint(
                painter,
                bounds,
                content.text,
                content.subtitle_style,
            )
            return
        if content.kind is ContentType.PDF_PAGE:
            draw_contained_image(painter, bounds.toRect(), pdf_image)
            return
        if content.kind is ContentType.VIDEO:
            draw_contained_image(painter, bounds.toRect(), video_frame)
            return
        painter.fillRect(bounds, "black")
