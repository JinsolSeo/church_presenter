from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath

from church_presenter.domain.enums import HorizontalAnchor, TextAlignment, VerticalAnchor
from church_presenter.domain.models import SubtitleStyle


class SubtitleRenderer:
    """Paint styled subtitles with normalized positioning."""

    REFERENCE_HEIGHT = 1080.0

    def paint(self, painter: QPainter, bounds: QRectF, text: str, style: SubtitleStyle) -> None:
        if not text:
            return
        scale = bounds.height() / self.REFERENCE_HEIGHT
        font = QFont(style.font_family)
        font.setPixelSize(max(8, round(style.font_size * scale)))
        font.setBold(style.bold)
        metrics = QFontMetricsF(font)
        max_width = max(40.0, bounds.width() * style.max_width_ratio)
        lines = self._wrapped_lines(text, metrics, max_width)
        line_height = metrics.height() * style.line_spacing
        text_height = max(metrics.height(), len(lines) * line_height)
        actual_width = min(
            max_width,
            max((metrics.horizontalAdvance(line) for line in lines), default=0.0),
        )
        padding = style.background_padding * scale
        box_width = min(bounds.width(), actual_width + padding * 2)
        box_height = text_height + padding * 2
        anchor = QPointF(
            bounds.x() + bounds.width() * style.x_ratio,
            bounds.y() + bounds.height() * style.y_ratio,
        )
        left = self._anchor_x(anchor.x(), box_width, style.horizontal_anchor)
        top = self._anchor_y(anchor.y(), box_height, style.vertical_anchor)
        box = QRectF(left, top, box_width, box_height)

        background = QColor(style.background_color)
        background.setAlphaF(max(0.0, min(1.0, style.background_opacity)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(box, 8 * scale, 8 * scale)

        baseline = box.top() + padding + metrics.ascent()
        content_left = box.left() + padding
        content_width = max(1.0, box.width() - padding * 2)
        for index, line in enumerate(lines):
            line_width = metrics.horizontalAdvance(line)
            x = self._line_x(content_left, content_width, line_width, style.alignment)
            y = baseline + index * line_height
            path = QPainterPath()
            path.addText(QPointF(x, y), font, line)

            shadow = QColor(style.shadow_color)
            shadow.setAlphaF(max(0.0, min(1.0, style.shadow_opacity)))
            painter.save()
            painter.translate(style.shadow_offset_x * scale, style.shadow_offset_y * scale)
            painter.fillPath(path, shadow)
            painter.restore()

            if style.outline_width > 0:
                outline_pen = painter.pen()
                outline_pen.setColor(QColor(style.outline_color))
                outline_pen.setWidthF(style.outline_width * scale)
                outline_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.strokePath(path, outline_pen)
            painter.fillPath(path, QColor(style.text_color))

    @staticmethod
    def _wrapped_lines(text: str, metrics: QFontMetricsF, max_width: float) -> list[str]:
        output: list[str] = []
        for paragraph in text.splitlines() or [""]:
            words = paragraph.split()
            if not words:
                output.append("")
                continue
            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                if metrics.horizontalAdvance(candidate) <= max_width:
                    current = candidate
                else:
                    output.extend(SubtitleRenderer._break_long_line(current, metrics, max_width))
                    current = word
            output.extend(SubtitleRenderer._break_long_line(current, metrics, max_width))
        return output

    @staticmethod
    def _break_long_line(text: str, metrics: QFontMetricsF, max_width: float) -> list[str]:
        if metrics.horizontalAdvance(text) <= max_width:
            return [text]
        lines: list[str] = []
        current = ""
        for character in text:
            if current and metrics.horizontalAdvance(current + character) > max_width:
                lines.append(current)
                current = character
            else:
                current += character
        if current:
            lines.append(current)
        return lines

    @staticmethod
    def _anchor_x(value: float, width: float, anchor: HorizontalAnchor) -> float:
        if anchor is HorizontalAnchor.LEFT:
            return value
        if anchor is HorizontalAnchor.RIGHT:
            return value - width
        return value - width / 2

    @staticmethod
    def _anchor_y(value: float, height: float, anchor: VerticalAnchor) -> float:
        if anchor is VerticalAnchor.TOP:
            return value
        if anchor is VerticalAnchor.BOTTOM:
            return value - height
        return value - height / 2

    @staticmethod
    def _line_x(
        left: float,
        width: float,
        line_width: float,
        alignment: TextAlignment,
    ) -> float:
        if alignment is TextAlignment.LEFT:
            return left
        if alignment is TextAlignment.RIGHT:
            return left + width - line_width
        return left + (width - line_width) / 2
