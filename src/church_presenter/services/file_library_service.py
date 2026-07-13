from __future__ import annotations

from pathlib import Path

from church_presenter.domain.enums import Availability, MediaType, SortField
from church_presenter.domain.models import FileItem

EXTENSIONS: dict[MediaType, set[str]] = {
    MediaType.SUBTITLE: {".txt"},
    MediaType.PDF: {".pdf"},
    MediaType.VIDEO: {".mp4", ".mov", ".mkv", ".avi"},
    MediaType.AUDIO: {".mp3", ".wav", ".m4a", ".flac", ".ogg"},
}


def item_from_path(path: Path, media_type: MediaType) -> FileItem:
    """Create a resilient library record for a path."""
    try:
        stat = path.stat()
    except OSError as error:
        return FileItem(
            path=path,
            display_name=path.name,
            modified_time=0,
            file_size=0,
            media_type=media_type,
            availability=Availability.UNAVAILABLE,
            error_message=str(error),
        )
    return FileItem(
        path=path,
        display_name=path.name,
        modified_time=stat.st_mtime,
        file_size=stat.st_size,
        media_type=media_type,
    )


def scan_library(folder: Path, media_type: MediaType) -> list[FileItem]:
    """Scan one directory without raising for a missing folder."""
    if not folder.is_dir():
        return []
    extensions = EXTENSIONS[media_type]
    try:
        paths = [
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in extensions
        ]
    except OSError:
        return []
    return [item_from_path(path, media_type) for path in paths]


def sort_items(
    items: list[FileItem],
    field: SortField,
    descending: bool = False,
) -> list[FileItem]:
    """Return a stable, cross-platform sorted copy."""
    if field is SortField.MODIFIED:
        return sorted(
            items,
            key=lambda item: (item.modified_time, item.display_name.casefold()),
            reverse=descending,
        )
    return sorted(
        items,
        key=lambda item: (item.display_name.casefold(), item.modified_time),
        reverse=descending,
    )
