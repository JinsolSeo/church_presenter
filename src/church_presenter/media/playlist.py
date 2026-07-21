from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from church_presenter.domain.enums import (
    AudioAvailability,
    AudioSourceType,
    RepeatMode,
)
from church_presenter.domain.models import AudioPlaylist, PlaylistItem
from church_presenter.media.youtube_resolver import validate_youtube_url

PLAYLIST_SCHEMA_VERSION = 2
YOUTUBE_URL_SCHEMA_VERSION = 1
YOUTUBE_URL_FILENAME = "youtube_url.json"


class PlaylistService:
    """Read, migrate, and atomically write portable JSON playlists."""

    def save(self, playlist: AudioPlaylist, path: Path) -> None:
        destination = path.expanduser().resolve()
        payload: dict[str, Any] = {
            "version": PLAYLIST_SCHEMA_VERSION,
            "name": playlist.name,
            "current_index": playlist.current_index,
            "repeat_mode": playlist.repeat_mode.value,
            "items": [self._item_to_dict(item, destination.parent) for item in playlist.items],
        }
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        playlist.name = destination.stem
        playlist.is_modified = False

    def load(self, path: Path) -> AudioPlaylist:
        source = path.expanduser().resolve()
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
            raise ValueError("playlist root or items are invalid")
        version = data.get("version", 1)
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or version not in {1, PLAYLIST_SCHEMA_VERSION}
        ):
            raise ValueError(f"unsupported playlist version: {version}")
        items = [self._item_from_dict(item, source.parent, version) for item in data["items"]]
        current = data.get("current_index")
        current_index = current if isinstance(current, int) and 0 <= current < len(items) else None
        try:
            repeat_mode = RepeatMode(str(data.get("repeat_mode", RepeatMode.NONE.value)))
        except ValueError as error:
            raise ValueError("playlist repeat_mode is invalid") from error
        playlist = AudioPlaylist(
            name=str(data.get("name", source.stem)),
            items=items,
            current_index=current_index,
            repeat_mode=repeat_mode,
            is_modified=False,
        )
        if playlist.items and playlist.current_index is None:
            playlist.current_index = 0
        return playlist

    def load_youtube_items(self, folder: Path) -> list[PlaylistItem]:
        """Load folder-scoped YouTube URLs, returning none when the file is absent."""
        source = folder.expanduser().resolve() / YOUTUBE_URL_FILENAME
        if not source.is_file():
            return []
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("youtube_url.json root must be an object")
        version = data.get("version")
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or version != YOUTUBE_URL_SCHEMA_VERSION
        ):
            raise ValueError(f"unsupported youtube_url.json version: {version}")
        entries = data.get("urls")
        if not isinstance(entries, list):
            raise ValueError("youtube_url.json urls must be a list")

        items: list[PlaylistItem] = []
        seen: set[str] = set()
        for entry in entries:
            raw_url: object
            if isinstance(entry, str):
                raw_url = entry
                fallback = None
            elif isinstance(entry, dict):
                raw_url = entry.get("url")
                fallback = self._optional_path(
                    entry.get("fallback_path"),
                    bool(entry.get("fallback_relative")),
                    source.parent,
                )
            else:
                raise ValueError("youtube_url.json URL entry is invalid")
            if not isinstance(raw_url, str):
                raise ValueError("youtube_url.json URL is invalid")
            url = validate_youtube_url(raw_url)
            if url in seen:
                continue
            seen.add(url)
            items.append(
                PlaylistItem.youtube(
                    uuid5(NAMESPACE_URL, url).hex,
                    url,
                    title="YouTube 정보 불러오는 중…",
                    fallback_path=fallback,
                )
            )
        return items

    def save_youtube_items(
        self,
        items: list[PlaylistItem],
        folder: Path,
    ) -> Path:
        """Atomically save only YouTube entries to the folder's fixed JSON file."""
        destination = folder.expanduser().resolve() / YOUTUBE_URL_FILENAME
        urls: list[dict[str, Any]] = []
        for item in items:
            if item.source_type is not AudioSourceType.YOUTUBE:
                continue
            entry: dict[str, Any] = {"url": validate_youtube_url(item.source)}
            if item.fallback_path is not None:
                fallback, relative = self._store_path(item.fallback_path, destination.parent)
                entry["fallback_path"] = fallback
                entry["fallback_relative"] = relative
            urls.append(entry)
        payload = {"version": YOUTUBE_URL_SCHEMA_VERSION, "urls": urls}
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    @classmethod
    def _item_to_dict(cls, item: PlaylistItem, base: Path) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": item.item_id,
            "source_type": item.source_type.value,
            "display_title": item.display_title,
            "duration_ms": item.duration_ms,
            "availability": item.availability.value,
            "error_message": item.error_message,
            "metadata": dict(item.metadata),
        }
        if item.source_type is AudioSourceType.LOCAL_FILE:
            if item.path is None:
                raise ValueError("local playlist item has no path")
            payload["source"], payload["source_relative"] = cls._store_path(item.path, base)
        else:
            payload["source"] = item.source
            payload["source_relative"] = False
        if item.fallback_path is not None:
            fallback, relative = cls._store_path(item.fallback_path, base)
            payload["fallback_path"] = fallback
            payload["fallback_relative"] = relative
        else:
            payload["fallback_path"] = None
            payload["fallback_relative"] = False
        return payload

    @classmethod
    def _item_from_dict(cls, data: object, base: Path, version: int) -> PlaylistItem:
        if not isinstance(data, dict):
            raise ValueError("playlist item is invalid")
        if version == 1:
            return cls._legacy_local_item(data, base)
        try:
            source_type = AudioSourceType(str(data["source_type"]))
        except (KeyError, ValueError) as error:
            raise ValueError("playlist source_type is invalid") from error
        source = data.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("playlist source is invalid")
        item_id = str(data.get("id", data.get("item_id", source)))
        title = str(data.get("display_title", data.get("title", source)))
        duration = data.get("duration_ms") if isinstance(data.get("duration_ms"), int) else None
        metadata_data = data.get("metadata", {})
        metadata = (
            {str(key): str(value) for key, value in metadata_data.items()}
            if isinstance(metadata_data, dict)
            else {}
        )
        fallback = cls._optional_path(
            data.get("fallback_path"),
            bool(data.get("fallback_relative")),
            base,
        )
        if source_type is AudioSourceType.LOCAL_FILE:
            path = cls._resolve_path(source, bool(data.get("source_relative")), base)
            available = path.is_file()
            return PlaylistItem(
                item_id=item_id,
                path=path,
                title=title,
                duration_ms=duration,
                is_available=available,
                error_message="" if available else "파일을 찾을 수 없습니다.",
                fallback_path=fallback,
                metadata=metadata,
            )
        try:
            availability = AudioAvailability(
                str(data.get("availability", AudioAvailability.UNRESOLVED.value))
            )
        except ValueError as error:
            raise ValueError("playlist availability is invalid") from error
        return PlaylistItem.youtube(
            item_id,
            source,
            title=title,
            duration_ms=duration,
            fallback_path=fallback,
            availability=availability,
            metadata=metadata,
            error_message=str(data.get("error_message", "")),
        )

    @classmethod
    def _legacy_local_item(cls, data: dict[str, Any], base: Path) -> PlaylistItem:
        raw = data.get("path")
        if not isinstance(raw, str):
            raise ValueError("version-1 playlist item is invalid")
        path = cls._resolve_path(raw, bool(data.get("relative")), base)
        available = path.is_file()
        return PlaylistItem(
            item_id=str(data.get("item_id", path)),
            path=path,
            title=str(data.get("title", path.stem)),
            duration_ms=(
                data.get("duration_ms") if isinstance(data.get("duration_ms"), int) else None
            ),
            is_available=available,
            error_message="" if available else "파일을 찾을 수 없습니다.",
        )

    @staticmethod
    def _store_path(path: Path, base: Path) -> tuple[str, bool]:
        resolved = path.expanduser().resolve()
        try:
            return str(resolved.relative_to(base)), True
        except ValueError:
            return str(resolved), False

    @staticmethod
    def _resolve_path(raw: str, relative: bool, base: Path) -> Path:
        path = Path(raw)
        return (base / path).resolve() if relative else path.expanduser().resolve()

    @classmethod
    def _optional_path(cls, raw: object, relative: bool, base: Path) -> Path | None:
        if raw is None:
            return None
        if not isinstance(raw, str) or not raw:
            raise ValueError("playlist fallback_path is invalid")
        return cls._resolve_path(raw, relative, base)
