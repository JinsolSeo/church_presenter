from __future__ import annotations

from enum import StrEnum


class ContentType(StrEnum):
    """Content kinds understood by output channels."""

    BLACK = "black"
    SUBTITLE_KEY = "subtitle_key"
    PDF_PAGE = "pdf_page"
    VIDEO = "video"


class ChannelRole(StrEnum):
    """Independent output roles."""

    BROADCAST = "broadcast"
    VENUE = "venue"


class MediaType(StrEnum):
    """Library media categories."""

    SUBTITLE = "subtitle"
    PDF = "pdf"
    VIDEO = "video"
    AUDIO = "audio"


class Availability(StrEnum):
    """File availability state."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class SortField(StrEnum):
    """Supported library sort fields."""

    NAME = "name"
    MODIFIED = "modified"


class PlaybackStatus(StrEnum):
    """Runtime state shared by replaceable media backends."""

    UNLOADED = "unloaded"
    LOADING = "loading"
    READY = "ready"
    CUE = "cue"
    LIVE_PAUSED = "live_paused"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    ENDED = "ended"
    ERROR = "error"


class RepeatMode(StrEnum):
    """Background-music playlist repeat policy."""

    NONE = "none"
    ONE = "one"
    ALL = "all"


class PauseReason(StrEnum):
    """Why background music is currently paused."""

    NONE = "none"
    USER = "user"
    VIDEO = "video"


class TextAlignment(StrEnum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class HorizontalAnchor(StrEnum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class VerticalAnchor(StrEnum):
    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"
