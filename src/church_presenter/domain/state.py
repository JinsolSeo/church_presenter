from __future__ import annotations

from dataclasses import dataclass, field

from church_presenter.domain.enums import ChannelRole, ContentType
from church_presenter.domain.models import Content


@dataclass(slots=True)
class ChannelState:
    """Preview/Live state for one output."""

    role: ChannelRole
    preview_content: Content = field(default_factory=Content.black)
    live_content: Content = field(default_factory=Content.black)
    is_ready: bool = True
    last_error: str = ""
    assigned_screen: str = ""

    @property
    def output_mode(self) -> ContentType:
        return self.live_content.kind

    def validate_preview(self) -> tuple[bool, str]:
        content = self.preview_content
        if not self.is_ready:
            return False, self.last_error or "Preview content is still preparing."
        if self.role is ChannelRole.VENUE and content.kind is ContentType.SUBTITLE_KEY:
            return False, "현장 출력은 자막을 지원하지 않습니다."
        if content.kind is ContentType.PDF_PAGE:
            if content.pdf_path is None or content.pdf_page is None:
                return False, "PDF page is incomplete."
            if not content.pdf_path.is_file():
                return False, "PDF file is unavailable."
        if content.kind is ContentType.VIDEO:
            if content.video_source is None:
                return False, "Video content is incomplete."
            if content.video_path is not None and not content.video_path.is_file():
                return False, "Video file is unavailable."
        return True, ""


@dataclass(slots=True)
class ApplicationState:
    """Central state and transactional output commands."""

    broadcast: ChannelState = field(default_factory=lambda: ChannelState(ChannelRole.BROADCAST))
    venue: ChannelState = field(default_factory=lambda: ChannelState(ChannelRole.VENUE))

    def channel(self, role: ChannelRole) -> ChannelState:
        return self.broadcast if role is ChannelRole.BROADCAST else self.venue

    def set_preview(self, role: ChannelRole, content: Content, *, ready: bool = True) -> None:
        channel = self.channel(role)
        channel.preview_content = content
        channel.is_ready = ready
        channel.last_error = "" if ready else "Preview content is still preparing."

    def mark_preview_ready(self, role: ChannelRole, ready: bool, error: str = "") -> None:
        channel = self.channel(role)
        channel.is_ready = ready
        channel.last_error = error

    def take(self, role: ChannelRole) -> tuple[bool, str]:
        channel = self.channel(role)
        valid, error = channel.validate_preview()
        if not valid:
            channel.last_error = error
            return False, error
        channel.live_content = channel.preview_content
        channel.last_error = ""
        return True, ""

    def take_both(self) -> tuple[bool, str]:
        broadcast_valid, broadcast_error = self.broadcast.validate_preview()
        venue_valid, venue_error = self.venue.validate_preview()
        if not broadcast_valid or not venue_valid:
            error = broadcast_error or venue_error
            if not broadcast_valid:
                self.broadcast.last_error = broadcast_error
            if not venue_valid:
                self.venue.last_error = venue_error
            return False, error
        broadcast_next = self.broadcast.preview_content
        venue_next = self.venue.preview_content
        self.broadcast.live_content = broadcast_next
        self.venue.live_content = venue_next
        self.broadcast.last_error = ""
        self.venue.last_error = ""
        return True, ""

    def black_all(self) -> None:
        black = Content.black()
        self.broadcast.preview_content = black
        self.broadcast.live_content = black
        self.venue.preview_content = black
        self.venue.live_content = black
        self.broadcast.is_ready = True
        self.venue.is_ready = True
