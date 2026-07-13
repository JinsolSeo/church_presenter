from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPainter

from church_presenter.services.pdf_service import contain_size


def draw_contained_image(painter: QPainter, bounds: QRect, image: QImage) -> None:
    """Draw an image centered inside black bounds without cropping."""
    painter.fillRect(bounds, "black")
    if image.isNull():
        return
    x, y, width, height = contain_size(
        image.width(), image.height(), bounds.width(), bounds.height()
    )
    painter.drawImage(QRect(bounds.x() + x, bounds.y() + y, width, height), image)
