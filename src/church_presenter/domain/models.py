from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from church_presenter.domain.enums import (
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

    @classmethod
    def black(cls) -> Content:
        return cls(ContentType.BLACK)

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
    status: PlaybackStatus = PlaybackStatus.UNLOADED
    position_ms: int = 0
    duration_ms: int = 0
    volume: float = 0.7
    is_muted: bool = False
    pause_reason: PauseReason = PauseReason.NONE
    error_message: str = ""


@dataclass(frozen=True, slots=True)
class PlaylistItem:
    """One stable playlist entry."""

    item_id: str
    path: Path
    title: str
    duration_ms: int | None = None
    is_available: bool = True
    error_message: str = ""


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
    sort_descending: bool = False
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
