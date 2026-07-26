from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QImage, QImageWriter, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from church_presenter.domain.enums import ContentType
from church_presenter.rendering.output_surface import OutputSurface

DEFAULT_CAPTURE_FPS = 8
MAX_FRAME_WIDTH = 1280
JPEG_QUALITY = 72
REMOTE_VIDEO_NOTICE = "영상 재생 중 · 원격은 정지 화면"


class FrameCaptureService(QObject):
    """Capture the active Qt window on the GUI thread at a bounded rate."""

    frame_ready = Signal(object, object)

    def __init__(
        self,
        application: QApplication,
        controller: QWidget,
        *,
        excluded: Callable[[QWidget], bool] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.application = application
        self.controller = controller
        self.excluded = excluded or (lambda _widget: False)
        self.current_target: QWidget | None = controller
        self.sequence = 0
        self.capture_count = 0
        self._client_count = 0
        self.timer = QTimer(self)
        self.timer.setInterval(round(1000 / DEFAULT_CAPTURE_FPS))
        self.timer.timeout.connect(self.capture)

    @Slot(int)
    def set_client_count(self, count: int) -> None:
        self._client_count = max(0, count)
        if count > 0 and not self.timer.isActive():
            self.timer.start()
            QTimer.singleShot(0, self.capture)
        elif count <= 0:
            self.timer.stop()

    def stop(self) -> None:
        self.timer.stop()

    @Slot()
    def capture(self) -> None:
        if self._client_count <= 0:
            return
        target = self._capture_target()
        if target is None:
            return
        pixmap = target.grab()
        if pixmap.isNull():
            return
        image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
        self._composite_native_video(target, image)
        if image.width() > MAX_FRAME_WIDTH:
            image = image.scaledToWidth(
                MAX_FRAME_WIDTH,
                Qt.TransformationMode.SmoothTransformation,
            )
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            return
        writer = QImageWriter(buffer, b"jpeg")
        writer.setQuality(JPEG_QUALITY)
        if not writer.write(image):
            return
        self.current_target = target
        self.sequence += 1
        self.capture_count += 1
        metadata: dict[str, object] = {
            "type": "frame",
            "width": image.width(),
            "height": image.height(),
            "window": "controller" if target is self.controller else "dialog",
            "sequence": self.sequence,
        }
        self.frame_ready.emit(data.data(), metadata)

    def _capture_target(self) -> QWidget | None:
        active = self.application.activeWindow()
        if (
            active is not None
            and active.isVisible()
            and active is not self.controller
            and not self.excluded(active)
        ):
            return active
        return self.controller if self.controller.isVisible() else None

    @staticmethod
    def _composite_native_video(target: QWidget, image: QImage) -> None:
        """Replace native video holes with the prepared first frame.

        In particular, Windows hardware-decoded QVideoFrame.toImage() can force an
        expensive GPU-to-CPU readback. Remote operation values responsive controls
        over live video motion, so the Controller chrome remains at 8 FPS while each
        native video rectangle deliberately shows its already-cached cue frame.
        """
        scale_x = image.width() / max(1, target.width())
        scale_y = image.height() / max(1, target.height())
        painter = QPainter(image)
        for surface in target.findChildren(OutputSurface):
            if (
                not surface.isVisibleTo(target)
                or surface.content.kind is not ContentType.VIDEO
                or not surface.video_native_frame.isValid()
            ):
                continue
            top_left = surface.mapTo(target, surface.rect().topLeft())
            area = QRectF(
                top_left.x() * scale_x,
                top_left.y() * scale_y,
                surface.width() * scale_x,
                surface.height() * scale_y,
            )
            painter.fillRect(area, Qt.GlobalColor.black)
            cue_frame = surface.video_frame
            if not cue_frame.isNull():
                frame_size = cue_frame.size()
                frame_size.scale(
                    round(area.width()),
                    round(area.height()),
                    Qt.AspectRatioMode.KeepAspectRatio,
                )
                destination = QRectF(
                    area.x() + (area.width() - frame_size.width()) / 2,
                    area.y() + (area.height() - frame_size.height()) / 2,
                    frame_size.width(),
                    frame_size.height(),
                )
                painter.drawImage(destination, cue_frame)
            notice_height = min(area.height(), max(22.0, 30.0 * scale_y))
            notice = QRectF(
                area.x(),
                area.bottom() - notice_height,
                area.width(),
                notice_height,
            )
            painter.fillRect(notice, QColor(0, 0, 0, 190))
            font = QFont(painter.font())
            font.setPixelSize(max(10, round(13 * min(scale_x, scale_y))))
            painter.setFont(font)
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(
                notice,
                Qt.AlignmentFlag.AlignCenter,
                REMOTE_VIDEO_NOTICE,
            )
        painter.end()
