from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from church_presenter.domain.enums import (
    AudioAvailability,
    AudioSourceType,
    Availability,
    ContentType,
    HorizontalAnchor,
    MediaType,
    PauseReason,
    PlaybackStatus,
    RepeatMode,
    SortField,
    TextAlignment,
    VerticalAnchor,
)


@dataclass(frozen=True, slots=True)
class SubtitleStyle:
    """Resolution-independent subtitle drawing style."""

    font_family: str = "Arial"
    font_size: float = 54.0
    text_color: str = "#FFFFFF"
    bold: bool = True
    outline_color: str = "#000000"
    outline_width: float = 3.0
    shadow_color: str = "#000000"
    shadow_opacity: float = 0.65
    shadow_offset_x: float = 4.0
    shadow_offset_y: float = 4.0
    background_color: str = "#000000"
    background_opacity: float = 0.45
    background_padding: float = 18.0
    x_ratio: float = 0.5
    y_ratio: float = 0.82
    max_width_ratio: float = 0.86
    line_spacing: float = 1.2
    alignment: TextAlignment = TextAlignment.CENTER
    horizontal_anchor: HorizontalAnchor = HorizontalAnchor.CENTER
    vertical_anchor: VerticalAnchor = VerticalAnchor.BOTTOM

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubtitleStyle:
        """Build a style while ignoring unknown future keys."""
        valid = {item.name for item in field_list(cls)}
        values = {key: value for key, value in data.items() if key in valid}
        if "alignment" in values:
            values["alignment"] = TextAlignment(values["alignment"])
        if "horizontal_anchor" in values:
            values["horizontal_anchor"] = HorizontalAnchor(values["horizontal_anchor"])
        if "vertical_anchor" in values:
            values["vertical_anchor"] = VerticalAnchor(values["vertical_anchor"])
        return cls(**values)


def field_list(model: type[Any]) -> tuple[Any, ...]:
    """Return dataclass fields without exposing dataclasses internals elsewhere."""
    return tuple(model.__dataclass_fields__.values())


@dataclass(frozen=True, slots=True)
class Content:
    """Immutable content snapshot copied between Preview and Live."""

    kind: ContentType
    text: str = ""
    subtitle_card_index: int | None = None
    pdf_path: Path | None = None
    pdf_page: int | None = None
    video_path: Path | None = None
    subtitle_style: SubtitleStyle = field(default_factory=SubtitleStyle)
    key_color: str = "#00FF00"
    background_color: str = "#000000"

    @classmethod
    def black(cls) -> Content:
        return cls(ContentType.BLACK)

    @classmethod
    def solid_color(cls, color: str) -> Content:
        """Create a full-frame blank screen filled with one RGB color."""
        normalized = color.strip().upper()
        if (
            len(normalized) != 7
            or not normalized.startswith("#")
            or any(character not in "0123456789ABCDEF" for character in normalized[1:])
        ):
            raise ValueError("solid color must use #RRGGBB format")
        if normalized == "#000000":
            return cls.black()
        return cls(ContentType.SOLID_COLOR, background_color=normalized)

    @classmethod
    def subtitle(
        cls,
        text: str,
        card_index: int,
        style: SubtitleStyle,
        key_color: str,
    ) -> Content:
        return cls(
            ContentType.SUBTITLE_KEY,
            text=text,
            subtitle_card_index=card_index,
            subtitle_style=style,
            key_color=key_color,
        )

    @classmethod
    def pdf(cls, path: Path, page: int) -> Content:
        return cls(ContentType.PDF_PAGE, pdf_path=path, pdf_page=page)

    @classmethod
    def video(cls, path: Path) -> Content:
        """Create a cueable local-video descriptor."""
        return cls(ContentType.VIDEO, video_path=path.expanduser().resolve())

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible content snapshot."""
        return {
            "kind": self.kind.value,
            "text": self.text,
            "subtitle_card_index": self.subtitle_card_index,
            "pdf_path": str(self.pdf_path) if self.pdf_path is not None else None,
            "pdf_page": self.pdf_page,
            "video_path": str(self.video_path) if self.video_path is not None else None,
            "subtitle_style": self.subtitle_style.to_dict(),
            "key_color": self.key_color,
            "background_color": self.background_color,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Content:
        """Restore a persisted content snapshot."""
        kind = ContentType(str(data["kind"]))
        style_data = data.get("subtitle_style", {})
        if not isinstance(style_data, dict):
            raise TypeError("subtitle_style must be an object")
        pdf_path = data.get("pdf_path")
        video_path = data.get("video_path")
        return cls(
            kind=kind,
            text=str(data.get("text", "")),
            subtitle_card_index=_optional_int(data.get("subtitle_card_index")),
            pdf_path=Path(pdf_path) if isinstance(pdf_path, str) and pdf_path else None,
            pdf_page=_optional_int(data.get("pdf_page")),
            video_path=Path(video_path) if isinstance(video_path, str) and video_path else None,
            subtitle_style=SubtitleStyle.from_dict(style_data),
            key_color=str(data.get("key_color", "#00FF00")),
            background_color=str(data.get("background_color", "#000000")),
        )

    def as_preset_reference(self) -> Content:
        """Return a file-independent cue containing only type and position."""
        if self.kind is ContentType.SUBTITLE_KEY:
            return Content(
                kind=self.kind,
                subtitle_card_index=self.subtitle_card_index,
            )
        if self.kind is ContentType.PDF_PAGE:
            return Content(kind=self.kind, pdf_page=self.pdf_page)
        if self.kind is ContentType.VIDEO:
            return Content(kind=self.kind)
        if self.kind is ContentType.SOLID_COLOR:
            return Content.solid_color(self.background_color)
        return Content.black()

    def to_preset_dict(self) -> dict[str, Any]:
        """Serialize a file-independent worship-order cue."""
        data: dict[str, Any] = {"kind": self.kind.value}
        if self.kind is ContentType.SUBTITLE_KEY:
            data["position"] = self.subtitle_card_index
        elif self.kind is ContentType.PDF_PAGE:
            data["position"] = self.pdf_page
        elif self.kind is ContentType.SOLID_COLOR:
            data["color"] = self.background_color
        return data

    @classmethod
    def from_preset_dict(cls, data: dict[str, Any]) -> Content:
        """Restore a file-independent worship-order cue."""
        kind = ContentType(str(data["kind"]))
        position = _optional_int(data.get("position"))
        if kind is ContentType.SUBTITLE_KEY:
            return cls(kind=kind, subtitle_card_index=position)
        if kind is ContentType.PDF_PAGE:
            return cls(kind=kind, pdf_page=position)
        if kind is ContentType.VIDEO:
            return cls(kind=kind)
        if kind is ContentType.SOLID_COLOR:
            return cls.solid_color(str(data.get("color", "#00FF00")))
        return cls.black()


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("expected an integer or null")
    return int(value)


@dataclass(frozen=True, slots=True)
class PreviewPreset:
    """Named Broadcast/Venue Preview pair used as a worship-order cue."""

    name: str
    broadcast_content: Content
    venue_content: Content

    def __post_init__(self) -> None:
        cleaned = self.name.strip()
        if not cleaned:
            raise ValueError("preset name cannot be blank")
        if len(cleaned) > 80:
            raise ValueError("preset name cannot exceed 80 characters")
        if cleaned != self.name:
            object.__setattr__(self, "name", cleaned)
        if self.venue_content.kind is ContentType.SUBTITLE_KEY:
            raise ValueError("venue preview cannot contain subtitles")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible preset."""
        return {
            "name": self.name,
            "broadcast_content": self.broadcast_content.to_dict(),
            "venue_content": self.venue_content.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PreviewPreset:
        """Restore a named Preview pair."""
        broadcast = data.get("broadcast_content")
        venue = data.get("venue_content")
        if not isinstance(broadcast, dict) or not isinstance(venue, dict):
            raise TypeError("preset content must be an object")
        return cls(
            name=str(data["name"]),
            broadcast_content=Content.from_dict(broadcast),
            venue_content=Content.from_dict(venue),
        )

    def as_file_independent(self) -> PreviewPreset:
        """Drop source paths and rendered text from this preset."""
        return PreviewPreset(
            self.name,
            self.broadcast_content.as_preset_reference(),
            self.venue_content.as_preset_reference(),
        )

    def to_preset_dict(self) -> dict[str, Any]:
        """Return the version-2 worship-order representation."""
        return {
            "name": self.name,
            "broadcast": self.broadcast_content.to_preset_dict(),
            "venue": self.venue_content.to_preset_dict(),
        }

    @classmethod
    def from_preset_dict(cls, data: dict[str, Any]) -> PreviewPreset:
        """Restore a version-2 file-independent worship-order preset."""
        broadcast = data.get("broadcast")
        venue = data.get("venue")
        if not isinstance(broadcast, dict) or not isinstance(venue, dict):
            raise TypeError("preset cues must be objects")
        return cls(
            name=str(data["name"]),
            broadcast_content=Content.from_preset_dict(broadcast),
            venue_content=Content.from_preset_dict(venue),
        )


@dataclass(slots=True)
class SubtitleDocument:
    """Editable source-line document; grouped cards are always derived."""

    path: Path | None = None
    lines: list[str] = field(default_factory=list)
    group_size: int = 2
    is_modified: bool = False

    @property
    def cards(self) -> list[str]:
        if self.group_size < 1:
            raise ValueError("group_size must be at least one")
        return [
            "\n".join(self.lines[index : index + self.group_size])
            for index in range(0, len(self.lines), self.group_size)
        ]

    def set_group_size(self, group_size: int) -> None:
        if group_size < 1:
            raise ValueError("group_size must be at least one")
        if group_size != self.group_size:
            self.group_size = group_size

    def edit_line(self, index: int, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("subtitle lines cannot be blank")
        if self.lines[index] != cleaned:
            self.lines[index] = cleaned
            self.is_modified = True

    def add_line(self, text: str, index: int | None = None) -> int:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("subtitle lines cannot be blank")
        target = len(self.lines) if index is None else index
        self.lines.insert(target, cleaned)
        self.is_modified = True
        return target

    def delete_line(self, index: int) -> str:
        removed = self.lines.pop(index)
        self.is_modified = True
        return removed

    def move_line(self, index: int, destination: int) -> int:
        if not 0 <= destination < len(self.lines):
            return index
        line = self.lines.pop(index)
        self.lines.insert(destination, line)
        if destination != index:
            self.is_modified = True
        return destination


@dataclass(frozen=True, slots=True)
class FileItem:
    path: Path
    display_name: str
    modified_time: float
    file_size: int
    media_type: MediaType
    availability: Availability = Availability.AVAILABLE
    error_message: str = ""


@dataclass(frozen=True, slots=True)
class MediaFileItem(FileItem):
    """Library item enriched with asynchronously discovered media metadata."""

    duration_ms: int | None = None
    resolution: tuple[int, int] | None = None
    playback_status: PlaybackStatus = PlaybackStatus.UNLOADED
    thumbnail_path: Path | None = None


@dataclass(slots=True)
class VideoPlaybackRuntimeState:
    """Mutable playback facts kept separate from immutable content."""

    path: Path | None = None
    status: PlaybackStatus = PlaybackStatus.UNLOADED
    position_ms: int = 0
    duration_ms: int = 0
    volume: float = 0.8
    is_muted: bool = False
    error_message: str = ""


@dataclass(slots=True)
class AudioPlaybackRuntimeState:
    """Global background-music playback state."""

    path: Path | None = None
    source_type: AudioSourceType | None = None
    source: str = ""
    title: str = ""
    status: PlaybackStatus = PlaybackStatus.UNLOADED
    position_ms: int = 0
    duration_ms: int = 0
    volume: float = 0.7
    is_muted: bool = False
    pause_reason: PauseReason = PauseReason.NONE
    error_message: str = ""
    using_fallback: bool = False
    status_message: str = ""


@dataclass(frozen=True, slots=True)
class PlaylistItem:
    """One stable playlist entry."""

    item_id: str
    path: Path | None
    title: str
    duration_ms: int | None = None
    is_available: bool = True
    error_message: str = ""
    source_type: AudioSourceType = AudioSourceType.LOCAL_FILE
    source: str = ""
    fallback_path: Path | None = None
    availability: AudioAvailability = AudioAvailability.READY
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize compatibility fields used by version-1 local playlists."""
        if self.source_type is AudioSourceType.LOCAL_FILE:
            if self.path is None:
                raise ValueError("local playlist items require a path")
            resolved = self.path.expanduser().resolve()
            object.__setattr__(self, "path", resolved)
            object.__setattr__(self, "source", self.source or str(resolved))
            state = AudioAvailability.READY if self.is_available else AudioAvailability.MISSING
            object.__setattr__(self, "availability", state)
        elif not self.source:
            raise ValueError("YouTube playlist items require a source URL")

    @property
    def display_title(self) -> str:
        """Return the title shown in the playlist UI."""
        return self.title

    @classmethod
    def youtube(
        cls,
        item_id: str,
        url: str,
        *,
        title: str = "YouTube 항목",
        duration_ms: int | None = None,
        fallback_path: Path | None = None,
        availability: AudioAvailability = AudioAvailability.UNRESOLVED,
        metadata: dict[str, str] | None = None,
        error_message: str = "",
    ) -> PlaylistItem:
        """Create a YouTube playlist item without inventing a local path."""
        return cls(
            item_id=item_id,
            path=None,
            title=title,
            duration_ms=duration_ms,
            is_available=availability is AudioAvailability.READY,
            error_message=error_message,
            source_type=AudioSourceType.YOUTUBE,
            source=url,
            fallback_path=fallback_path.expanduser().resolve() if fallback_path else None,
            availability=availability,
            metadata=dict(metadata or {}),
        )


@dataclass(slots=True)
class AudioPlaylist:
    """UI-independent ordered background-music playlist."""

    name: str = "새 재생목록"
    items: list[PlaylistItem] = field(default_factory=list)
    current_index: int | None = None
    repeat_mode: RepeatMode = RepeatMode.NONE
    is_modified: bool = False

    def add(self, item: PlaylistItem) -> None:
        self.items.append(item)
        if self.current_index is None:
            self.current_index = 0
        self.is_modified = True

    def remove(self, index: int) -> PlaylistItem:
        removed = self.items.pop(index)
        if not self.items:
            self.current_index = None
        elif self.current_index is not None:
            if index < self.current_index:
                self.current_index -= 1
            elif self.current_index >= len(self.items):
                self.current_index = len(self.items) - 1
        self.is_modified = True
        return removed

    def clear(self) -> None:
        if self.items:
            self.items.clear()
            self.current_index = None
            self.is_modified = True

    def move(self, source: int, destination: int) -> int:
        if not (0 <= source < len(self.items) and 0 <= destination < len(self.items)):
            return source
        current_id = self.current_item.item_id if self.current_item else None
        item = self.items.pop(source)
        self.items.insert(destination, item)
        if current_id is not None:
            self.current_index = next(
                index
                for index, candidate in enumerate(self.items)
                if candidate.item_id == current_id
            )
        if source != destination:
            self.is_modified = True
        return destination

    @property
    def current_item(self) -> PlaylistItem | None:
        if self.current_index is None or not 0 <= self.current_index < len(self.items):
            return None
        return self.items[self.current_index]

    def next_index(self, *, ended: bool = False) -> int | None:
        if not self.items:
            return None
        index = self.current_index if self.current_index is not None else 0
        if ended and self.repeat_mode is RepeatMode.ONE:
            return index
        if index + 1 < len(self.items):
            return index + 1
        if self.repeat_mode is RepeatMode.ALL:
            return 0
        return None

    def previous_index(self, position_ms: int, threshold_ms: int = 3000) -> int | None:
        if not self.items:
            return None
        index = self.current_index if self.current_index is not None else 0
        if position_ms >= threshold_ms:
            return index
        if index > 0:
            return index - 1
        if self.repeat_mode is RepeatMode.ALL:
            return len(self.items) - 1
        return index


@dataclass(frozen=True, slots=True)
class ScreenInfo:
    id: str
    name: str
    x: int
    y: int
    width: int
    height: int
    device_pixel_ratio: float = 1.0
    is_primary: bool = False
    is_connected: bool = True

    @property
    def label(self) -> str:
        primary = " · Primary" if self.is_primary else ""
        return (
            f"{self.name} · {self.width}x{self.height} @ {self.x},{self.y} "
            f"· {self.device_pixel_ratio:.2f}x{primary}"
        )


@dataclass(slots=True)
class AppSettings:
    """Persisted application settings."""

    version: int = 1
    subtitle_folder: str = ""
    pdf_folder: str = ""
    video_folder: str = ""
    audio_folder: str = ""
    sort_field: SortField = SortField.NAME
    sort_descending: bool = True
    video_sort_field: SortField = SortField.NAME
    video_sort_descending: bool = False
    audio_sort_field: SortField = SortField.NAME
    audio_sort_descending: bool = False
    controller_screen_id: str = ""
    broadcast_screen_id: str = ""
    venue_screen_id: str = ""
    simulation_mode: bool = False
    simulation_width: int = 1280
    simulation_height: int = 720
    simulation_dpr: float = 1.0
    simulation_broadcast_connected: bool = True
    simulation_venue_connected: bool = True
    controller_geometry: str = ""
    panel_layout: str = "tabs:0"
    workspace_splitter_state: str = ""
    current_theme: str = "light_professional"
    preview_preset_file: str = ""
    last_subtitle_file: str = ""
    subtitle_group_size: int = 2
    last_pdf_file: str = ""
    last_pdf_page: int = 0
    pdf_page_orders: dict[str, list[int]] = field(default_factory=dict)
    pdf_link_outputs: bool = False
    subtitle_pdf_linked: bool = False
    current_style_preset: str = "Lower Third"
    key_color: str = "#00FF00"
    fade_duration_ms: int = 250
    video_volume: int = 80
    music_volume: int = 70
    video_muted: bool = False
    music_muted: bool = False
    audio_output_device_id: str = ""
    last_video_file: str = ""
    last_audio_file: str = ""
    last_playlist: str = ""
    recent_playlists: list[str] = field(default_factory=list)
    repeat_mode: RepeatMode = RepeatMode.NONE
    audio_position_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettings:
        valid = {item.name for item in field_list(cls)}
        values = {key: value for key, value in data.items() if key in valid}
        if "sort_field" in values:
            values["sort_field"] = SortField(values["sort_field"])
        for key in ("video_sort_field", "audio_sort_field"):
            if key in values:
                values[key] = SortField(values[key])
        if "repeat_mode" in values:
            values["repeat_mode"] = RepeatMode(values["repeat_mode"])
        page_orders = values.get("pdf_page_orders")
        if isinstance(page_orders, dict):
            values["pdf_page_orders"] = {
                str(path): [page for page in order if isinstance(page, int)]
                for path, order in page_orders.items()
                if isinstance(order, list)
            }
        else:
            values["pdf_page_orders"] = {}
        return cls(**values)

    def copy(self, **changes: Any) -> AppSettings:
        return replace(self, **changes)
