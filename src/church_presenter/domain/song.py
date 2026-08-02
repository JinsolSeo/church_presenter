from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class SongSectionType(StrEnum):
    VERSE = "verse"
    CHORUS = "chorus"
    BRIDGE = "bridge"

    @property
    def display_name(self) -> str:
        return {
            SongSectionType.VERSE: "Verse",
            SongSectionType.CHORUS: "Chorus",
            SongSectionType.BRIDGE: "Bridge",
        }[self]


@dataclass(frozen=True, slots=True)
class SongSection:
    id: str
    type: SongSectionType
    label: str
    lines: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.id):
            raise ValueError(f"invalid song section id {self.id!r}")
        if not self.label.strip():
            raise ValueError("song section label cannot be blank")
        if not self.lines:
            raise ValueError(f"song section {self.id!r} must contain lyrics")
        cleaned = tuple(line.strip() for line in self.lines)
        if any(not line for line in cleaned):
            raise ValueError(f"song section {self.id!r} cannot contain blank lyrics")
        if cleaned != self.lines:
            object.__setattr__(self, "lines", cleaned)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "label": self.label,
            "lines": list(self.lines),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SongSection:
        lines = data.get("lines")
        if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
            raise TypeError("song section lines must be a list of strings")
        return cls(
            id=str(data.get("id", "")),
            type=SongSectionType(str(data.get("type", ""))),
            label=str(data.get("label", "")),
            lines=tuple(lines),
        )


@dataclass(frozen=True, slots=True)
class SongDocument:
    id: str
    title: str
    artist: str
    sections: tuple[SongSection, ...]
    default_sequence: tuple[str, ...]
    schema_version: int = 1

    DOCUMENT_TYPE = "church_presenter_song"

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("only song schema version 1 is supported")
        if not self.id.strip() or any(character in self.id for character in "\x00\r\n"):
            raise ValueError(f"invalid song id {self.id!r}")
        if not self.title.strip():
            raise ValueError("song title cannot be blank")
        if not self.sections:
            raise ValueError("song must contain at least one section")
        section_ids = tuple(section.id for section in self.sections)
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("song section ids must be unique")
        if not self.default_sequence:
            raise ValueError("song default_sequence cannot be empty")
        unknown = [
            section_id
            for section_id in self.default_sequence
            if section_id not in section_ids
        ]
        if unknown:
            raise ValueError(f"song default_sequence contains unknown sections: {unknown}")

    def section(self, section_id: str) -> SongSection:
        for section in self.sections:
            if section.id == section_id:
                return section
        raise KeyError(f"unknown song section {self.id}.{section_id}")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "document_type": self.DOCUMENT_TYPE,
            "title": self.title,
            "sections": [section.to_dict() for section in self.sections],
            "default_sequence": list(self.default_sequence),
        }
        if self.id != self.title:
            payload["id"] = self.id
        if self.artist:
            payload["artist"] = self.artist
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SongDocument:
        if data.get("document_type") != cls.DOCUMENT_TYPE:
            raise ValueError(f"expected document_type {cls.DOCUMENT_TYPE!r}")
        sections = data.get("sections")
        sequence = data.get("default_sequence")
        if not isinstance(sections, list) or not all(isinstance(row, dict) for row in sections):
            raise TypeError("song sections must be a list of objects")
        if not isinstance(sequence, list) or not all(isinstance(row, str) for row in sequence):
            raise TypeError("song default_sequence must be a list of strings")
        version = data.get("schema_version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise TypeError("song schema_version must be an integer")
        return cls(
            schema_version=version,
            id=str(data.get("id", data.get("title", ""))),
            title=str(data.get("title", "")),
            artist=str(data.get("artist", "")),
            sections=tuple(SongSection.from_dict(row) for row in sections),
            default_sequence=tuple(sequence),
        )


@dataclass(frozen=True, slots=True)
class SongPlanEntry:
    entry_id: str
    song_path: Path
    song: SongDocument
    sequence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.entry_id or any(character in self.entry_id for character in ":/"):
            raise ValueError("invalid song plan entry id")
        for section_id in self.sequence:
            self.song.section(section_id)
        if not self.sequence:
            raise ValueError("song plan entry sequence cannot be empty")

    @classmethod
    def create(
        cls,
        song_path: Path,
        song: SongDocument,
        sequence: tuple[str, ...],
    ) -> SongPlanEntry:
        return cls(uuid4().hex, song_path.expanduser().resolve(), song, sequence)


@dataclass(frozen=True, slots=True)
class SongCue:
    entry_id: str
    occurrence: int
    section_id: str
    line_start: int
    line_end: int
    text: str

    @property
    def reference(self) -> str:
        return f"song:{self.entry_id}:{self.occurrence}:{self.line_start}"

    @classmethod
    def parse_reference(cls, value: str) -> tuple[str, int, int]:
        parts = value.split(":")
        if len(parts) != 4 or parts[0] != "song":
            raise ValueError(f"invalid song cue reference {value!r}")
        return parts[1], int(parts[2]), int(parts[3])
