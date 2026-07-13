from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from church_presenter.domain.enums import RepeatMode
from church_presenter.domain.models import AudioPlaylist, PlaylistItem


class PlaylistService:
    """Read and atomically write portable JSON playlists."""

    def save(self, playlist: AudioPlaylist, path: Path) -> None:
        destination = path.expanduser().resolve()
        payload: dict[str, Any] = {
            "version": 1,
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
        items = [self._item_from_dict(item, source.parent) for item in data["items"]]
        current = data.get("current_index")
        current_index = current if isinstance(current, int) and 0 <= current < len(items) else None
        playlist = AudioPlaylist(
            name=str(data.get("name", source.stem)),
            items=items,
            current_index=current_index,
            repeat_mode=RepeatMode(str(data.get("repeat_mode", RepeatMode.NONE.value))),
            is_modified=False,
        )
        if playlist.items and playlist.current_index is None:
            playlist.current_index = 0
        return playlist

    @staticmethod
    def _item_to_dict(item: PlaylistItem, base: Path) -> dict[str, Any]:
        try:
            stored_path = str(item.path.resolve().relative_to(base))
            relative = True
        except ValueError:
            stored_path = str(item.path.resolve())
            relative = False
        return {
            "item_id": item.item_id,
            "path": stored_path,
            "relative": relative,
            "title": item.title,
            "duration_ms": item.duration_ms,
        }

    @staticmethod
    def _item_from_dict(data: object, base: Path) -> PlaylistItem:
        if not isinstance(data, dict) or not isinstance(data.get("path"), str):
            raise ValueError("playlist item is invalid")
        raw_path = Path(data["path"])
        path = (
            (base / raw_path).resolve() if data.get("relative") else raw_path.expanduser().resolve()
        )
        available = path.is_file()
        return PlaylistItem(
            item_id=str(data.get("item_id", path)),
            path=path,
            title=str(data.get("title", path.stem)),
            duration_ms=data.get("duration_ms")
            if isinstance(data.get("duration_ms"), int)
            else None,
            is_available=available,
            error_message="" if available else "파일을 찾을 수 없습니다.",
        )
