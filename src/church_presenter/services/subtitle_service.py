from __future__ import annotations

import os
from pathlib import Path

from church_presenter.domain.models import SubtitleDocument


def parse_subtitle_text(text: str) -> list[str]:
    """Parse one source subtitle per non-empty line."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return [line.strip() for line in normalized.split("\n") if line.strip()]


def load_subtitle(path: Path, group_size: int = 2) -> SubtitleDocument:
    """Load UTF-8 or UTF-8-SIG text without preserving blank source lines."""
    text = path.read_text(encoding="utf-8-sig")
    return SubtitleDocument(path=path, lines=parse_subtitle_text(text), group_size=group_size)


def save_subtitle(document: SubtitleDocument, path: Path | None = None) -> Path:
    """Atomically save source lines as UTF-8 without BOM."""
    destination = path or document.path
    if destination is None:
        raise ValueError("A destination path is required")
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    payload = "\n".join(line.strip() for line in document.lines if line.strip()) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    document.path = destination
    document.lines = parse_subtitle_text(payload)
    document.is_modified = False
    return destination
