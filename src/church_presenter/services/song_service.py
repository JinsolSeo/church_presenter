from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from church_presenter.domain.song import SongDocument, SongPlanEntry
from church_presenter.services.json_io import atomic_write_json, read_json_object

SONG_PLAN_DOCUMENT_TYPE = "church_presenter_song_plan"


def load_song(path: Path) -> SongDocument:
    return SongDocument.from_dict(read_json_object(path.expanduser().resolve()))


def save_song(path: Path, song: SongDocument) -> Path:
    destination = path.expanduser().resolve()
    atomic_write_json(destination, song.to_dict())
    return destination


def save_song_plan(path: Path, entries: list[SongPlanEntry]) -> Path:
    destination = path.expanduser().resolve()
    rows: list[dict[str, Any]] = []
    for entry in entries:
        try:
            source = os.path.relpath(entry.song_path, destination.parent)
        except ValueError:
            source = str(entry.song_path)
        rows.append(
            {
                "entry_id": entry.entry_id,
                "song_source": source,
                "song_id": entry.song.id,
                "sequence": list(entry.sequence),
            }
        )
    atomic_write_json(
        destination,
        {
            "schema_version": 1,
            "document_type": SONG_PLAN_DOCUMENT_TYPE,
            "entries": rows,
        },
    )
    return destination


def load_song_plan(path: Path) -> list[SongPlanEntry]:
    source = path.expanduser().resolve()
    payload = read_json_object(source)
    if (
        payload.get("document_type") != SONG_PLAN_DOCUMENT_TYPE
        or payload.get("schema_version") != 1
    ):
        raise ValueError("지원하지 않는 찬양 콘티 파일입니다")
    rows = payload.get("entries")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise TypeError("song plan entries must be a list of objects")
    entries: list[SongPlanEntry] = []
    seen_entry_ids: set[str] = set()
    for row in rows:
        song_source = row.get("song_source")
        sequence = row.get("sequence")
        if not isinstance(song_source, str) or not song_source:
            raise TypeError("song_source must be a non-empty string")
        if not isinstance(sequence, list) or not all(isinstance(item, str) for item in sequence):
            raise TypeError("song plan sequence must be a list of strings")
        song_path = Path(song_source)
        if not song_path.is_absolute():
            song_path = source.parent / song_path
        song_path = song_path.resolve()
        song = load_song(song_path)
        if song.id != str(row.get("song_id", "")):
            raise ValueError(f"찬양 콘티의 곡 ID가 파일과 다릅니다: {song_path.name}")
        entry_id = str(row.get("entry_id", ""))
        if entry_id in seen_entry_ids:
            raise ValueError(f"duplicate song plan entry id {entry_id!r}")
        seen_entry_ids.add(entry_id)
        entries.append(SongPlanEntry(entry_id, song_path, song, tuple(sequence)))
    return entries
