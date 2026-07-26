from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from church_presenter.domain.models import SubtitleDocument
from church_presenter.services.subtitle_service import parse_subtitle_text, save_subtitle


def padding_count(line_count: int, group_size: int) -> int:
    """Return the blank-line padding needed to end on a card boundary."""
    if line_count < 0:
        raise ValueError("line_count must not be negative")
    if group_size < 1:
        raise ValueError("group_size must be at least one")
    return (group_size - (line_count % group_size)) % group_size


def read_subtitle_lines(path: Path) -> list[str]:
    """Read a merge source as UTF-8 or UTF-8-SIG subtitle lines."""
    return parse_subtitle_text(path.read_text(encoding="utf-8-sig"))


def merge_subtitle_files(paths: Sequence[Path], group_size: int) -> SubtitleDocument:
    """Merge ordered subtitle files, padding every boundary to a complete card."""
    if not paths:
        raise ValueError("합칠 자막 파일을 하나 이상 선택하십시오.")
    if group_size < 1:
        raise ValueError("한 번에 표시할 자막 수는 1개 이상이어야 합니다.")

    merged_lines: list[str] = []
    for index, path in enumerate(paths):
        lines = read_subtitle_lines(path)
        merged_lines.extend(lines)
        if index < len(paths) - 1:
            merged_lines.extend("" for _ in range(padding_count(len(lines), group_size)))

    return SubtitleDocument(lines=merged_lines, group_size=group_size, is_modified=True)


def save_merged_subtitle(
    paths: Sequence[Path],
    destination: Path,
    group_size: int,
) -> Path:
    """Merge ordered subtitle files and atomically save the resulting TXT file."""
    resolved_sources = {path.expanduser().resolve() for path in paths}
    resolved_destination = destination.expanduser().resolve()
    if resolved_destination in resolved_sources:
        raise ValueError("원본 자막 파일과 다른 이름으로 저장하십시오.")
    document = merge_subtitle_files(paths, group_size)
    return save_subtitle(document, resolved_destination)
