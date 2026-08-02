from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtMultimedia import QVideoFrame, QVideoFrameFormat
from PySide6.QtWidgets import QApplication

from church_presenter.domain.enums import TextAlignment
from church_presenter.domain.models import Content, SubtitleStyle
from church_presenter.rendering.output_surface import OutputSurface
from church_presenter.rendering.subtitle_renderer import SubtitleRenderer
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

    assert window.windowTitle() == "송출 출력"
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


def test_output_surface_uses_native_video_frame_until_content_changes(
    qtbot,
    tmp_path: Path,
) -> None:
    path = tmp_path / "native-frame.mp4"
    path.write_bytes(b"test")
    surface = OutputSurface(PdfRenderCoordinator())
    qtbot.addWidget(surface)
    surface.resize(320, 180)
    surface.show()
    surface.set_content(Content.video(path))

    preview = QImage(320, 180, QImage.Format.Format_RGB32)
    preview.fill(Qt.GlobalColor.blue)
    surface.set_video_frame(str(path.resolve()), preview)
    assert not surface.video_widget.isVisible()

    frame = QVideoFrame(
        QVideoFrameFormat(
            QSize(320, 180),
            QVideoFrameFormat.PixelFormat.Format_RGBA8888,
        )
    )
    assert frame.isValid()
    surface.set_video_frame(str(path.resolve()), frame)

    assert surface.video_widget.isVisible()
    assert surface.video_widget.videoSink().videoFrame().isValid()

    surface.set_content(Content.black())
    assert not surface.video_widget.isVisible()
    assert not surface.video_widget.videoSink().videoFrame().isValid()


def test_bible_reference_inherits_body_effects_but_keeps_font_and_alignment(
    qtbot,
    monkeypatch,
) -> None:
    body = SubtitleStyle(
        outline_color="#112233",
        outline_width=7,
        shadow_color="#223344",
        shadow_opacity=0.8,
        shadow_offset_x=9,
        shadow_offset_y=11,
        background_color="#334455",
        background_opacity=0.9,
        background_padding=24,
    )
    reference = SubtitleStyle(
        font_family="Courier",
        font_size=25,
        text_color="#ABCDEF",
        bold=False,
        outline_color="#FF0000",
        outline_width=1,
        shadow_color="#00FF00",
        alignment=TextAlignment.LEFT,
    )
    renderer = SubtitleRenderer()
    painted: list[tuple[SubtitleStyle, bool]] = []
    original = renderer._paint_box

    def record(*args, **kwargs) -> None:
        painted.append((args[7], bool(kwargs["draw_background"])))
        original(*args, **kwargs)

    monkeypatch.setattr(renderer, "_paint_box", record)
    image = QImage(1280, 720, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.green)
    painter = QPainter(image)
    renderer.paint_stacked(
        painter,
        QRectF(image.rect()),
        "성경 본문",
        body,
        "마태복음 1:1-5",
        reference,
    )
    painter.end()

    inherited, draws_own_background = painted[0]
    assert inherited.font_family == reference.font_family
    assert inherited.font_size == reference.font_size
    assert inherited.text_color == reference.text_color
    assert inherited.bold == reference.bold
    assert inherited.alignment is reference.alignment
    assert inherited.outline_color == body.outline_color
    assert inherited.outline_width == body.outline_width
    assert inherited.shadow_color == body.shadow_color
    assert inherited.shadow_opacity == body.shadow_opacity
    assert inherited.shadow_offset_x == body.shadow_offset_x
    assert inherited.shadow_offset_y == body.shadow_offset_y
    assert inherited.background_color == body.background_color
    assert inherited.background_opacity == body.background_opacity
    assert inherited.background_padding == body.background_padding
    assert not draws_own_background
    assert not painted[1][1]
