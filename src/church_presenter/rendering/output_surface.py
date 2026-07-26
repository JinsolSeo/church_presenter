from __future__ import annotations

from uuid import uuid4

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QImage, QPainter, QPaintEvent, QResizeEvent
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QSizePolicy, QWidget

from church_presenter.domain.enums import ContentType
from church_presenter.domain.models import Content
from church_presenter.rendering.content_renderer import ContentRenderer
from church_presenter.services.pdf_service import PdfRenderCoordinator
from church_presenter.services.transition_service import TransitionService


class OutputSurface(QWidget):
    """The shared content surface used by every output context."""

    pdf_ready = Signal(bool, str)

    def __init__(
        self,
        coordinator: PdfRenderCoordinator,
        parent: QWidget | None = None,
        *,
        render_scale: float | None = None,
    ) -> None:
        super().__init__(parent)
        self.coordinator = coordinator
        self.renderer = ContentRenderer()
        self.render_scale = render_scale
        self.content = Content.black()
        self.pdf_image = QImage()
        self.video_frame = QImage()
        self.video_native_frame = QVideoFrame()
        self._video_frame_path = ""
        self._pending_content: Content | None = None
        self._opacity = 1.0
        self._native_video_allowed = True
        self._token = ""
        self.setMinimumSize(160, 90)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.video_widget = QVideoWidget(self)
        self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video_widget.setCursor(Qt.CursorShape.BlankCursor)
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.video_widget.setStyleSheet("background: black;")
        self.video_widget.hide()
        self.coordinator.rendered.connect(self._rendered)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(100)
        self._resize_timer.timeout.connect(self._request_pdf)
        self._fade_out = QVariantAnimation(self)
        self._fade_in = QVariantAnimation(self)
        for animation in (self._fade_out, self._fade_in):
            animation.setEasingCurve(QEasingCurve.Type.Linear)
            animation.valueChanged.connect(self._fade_value_changed)
        self._fade_out.finished.connect(self._fade_out_finished)
        self._fade_in.finished.connect(self._fade_in_finished)

    def set_content(self, content: Content, fade_duration_ms: int = 0) -> None:
        transition = TransitionService(fade_duration_ms)
        if transition.should_fade(self.content.kind, content.kind):
            self._freeze_native_video()
            self._native_video_allowed = False
            self.video_widget.hide()
            self._fade_out.stop()
            self._fade_in.stop()
            self._pending_content = content
            self._fade_out.setDuration(max(1, transition.fade_duration_ms // 2))
            self._fade_out.setStartValue(self._opacity)
            self._fade_out.setEndValue(0.0)
            self._fade_out.start()
            return
        self._fade_out.stop()
        self._fade_in.stop()
        self._opacity = 1.0
        self._native_video_allowed = True
        self._pending_content = None
        self._apply_content(content)

    @property
    def target_content(self) -> Content:
        """Return the content being displayed or currently fading in."""
        return self._pending_content or self.content

    def _apply_content(self, content: Content) -> None:
        self.coordinator.cancel(self._token)
        self.content = content
        self.pdf_image = QImage()
        if (
            content.kind is not ContentType.VIDEO
            or str(content.video_path or "") != self._video_frame_path
        ):
            self.video_frame = QImage()
            self.video_native_frame = QVideoFrame()
            self.video_widget.videoSink().setVideoFrame(QVideoFrame())
            self._video_frame_path = ""
        self._token = uuid4().hex
        self._sync_video_widget()
        self.update()
        self._request_pdf()

    def set_video_frame(self, path: str, frame: object) -> None:
        """Update a real decoded frame for current or pending video content."""
        current_path = str(self.content.video_path or "")
        pending_path = str(self._pending_content.video_path or "") if self._pending_content else ""
        if path not in (current_path, pending_path):
            return
        self._video_frame_path = path
        if isinstance(frame, QVideoFrame):
            if not frame.isValid():
                return
            self.video_native_frame = QVideoFrame(frame)
            self.video_widget.videoSink().setVideoFrame(self.video_native_frame)
            self._sync_video_widget()
            return
        if not isinstance(frame, QImage) or frame.isNull():
            return
        self.video_native_frame = QVideoFrame()
        self.video_widget.videoSink().setVideoFrame(QVideoFrame())
        self.video_frame = QImage(frame)
        self._sync_video_widget()
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)
        self.renderer.paint(
            painter,
            QRectF(self.rect()),
            self.content,
            self.pdf_image,
            self.video_frame,
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.video_widget.setGeometry(self.rect())
        if self.content.kind is ContentType.PDF_PAGE:
            self._resize_timer.start()

    def _request_pdf(self) -> None:
        if self.content.kind is not ContentType.PDF_PAGE:
            return
        if self.content.pdf_path is None or self.content.pdf_page is None:
            self.pdf_ready.emit(False, "PDF page is incomplete.")
            return
        scale = self.render_scale or self.devicePixelRatioF()
        target = QSize(
            max(1, round(self.width() * scale)),
            max(1, round(self.height() * scale)),
        )
        token = self._token
        self.coordinator.request(
            self.content.pdf_path,
            self.content.pdf_page,
            target,
            token,
            priority=1,
        )

    def _rendered(self, _key: object, image: QImage, error: str, token: object) -> None:
        if token != self._token:
            return
        if error:
            self.pdf_ready.emit(False, error)
            return
        self.pdf_image = image
        self.update()
        self.pdf_ready.emit(True, "")

    def _fade_value_changed(self, value: object) -> None:
        if not isinstance(value, (float, int)):
            return
        self._opacity = float(value)
        self.update()

    def _fade_out_finished(self) -> None:
        pending = self._pending_content
        self._pending_content = None
        if pending is None:
            return
        duration = self._fade_out.duration()
        self._apply_content(pending)
        self._fade_in.setDuration(duration)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.start()

    def _fade_in_finished(self) -> None:
        self._opacity = 1.0
        self._native_video_allowed = True
        self._sync_video_widget()
        self.update()

    def _freeze_native_video(self) -> None:
        if not self.video_native_frame.isValid():
            return
        image = self.video_native_frame.toImage()
        if not image.isNull():
            self.video_frame = image

    def _sync_video_widget(self) -> None:
        show_native = (
            self._native_video_allowed
            and self.content.kind is ContentType.VIDEO
            and str(self.content.video_path or "") == self._video_frame_path
            and self.video_native_frame.isValid()
        )
        self.video_widget.setVisible(show_native)
        if show_native:
            self.video_widget.raise_()


class AspectRatioContainer(QWidget):
    """Maintain a 16:9 child surface while the container resizes."""

    def __init__(self, child: QWidget, ratio: float = 16 / 9) -> None:
        super().__init__()
        self.child = child
        self.ratio = ratio
        child.setParent(self)
        self.setMinimumSize(160, 90)

    def resizeEvent(self, event: QResizeEvent) -> None:
        available = event.size()
        width = available.width()
        height = round(width / self.ratio)
        if height > available.height():
            height = available.height()
            width = round(height * self.ratio)
        self.child.setGeometry(
            (available.width() - width) // 2,
            (available.height() - height) // 2,
            width,
            height,
        )
