from __future__ import annotations

from pathlib import Path

import pytest

from church_presenter.domain.models import SubtitleDocument
from church_presenter.services.subtitle_service import (
    load_subtitle,
    parse_subtitle_text,
    save_subtitle,
)


def test_parse_one_source_per_non_empty_line() -> None:
    assert parse_subtitle_text(" first sentence. Second?\n\n 셋째 줄 \r\n") == [
        "first sentence. Second?",
        "셋째 줄",
    ]


def test_load_utf8_sig(tmp_path: Path) -> None:
    path = tmp_path / "bom.txt"
    path.write_text("첫 줄\n둘째 줄\n", encoding="utf-8-sig")
    document = load_subtitle(path, 2)
    assert document.lines == ["첫 줄", "둘째 줄"]
    assert document.cards == ["첫 줄\n둘째 줄"]


def test_grouping_is_derived_and_group_size_keeps_source() -> None:
    document = SubtitleDocument(lines=["1", "2", "3", "4", "5"], group_size=2)
    assert document.cards == ["1\n2", "3\n4", "5"]
    original = document.lines.copy()
    document.set_group_size(3)
    assert document.lines == original
    assert document.cards == ["1\n2\n3", "4\n5"]
    assert document.is_modified is False


def test_edit_add_delete_and_move_recompute_cards() -> None:
    document = SubtitleDocument(lines=["A", "B", "C"], group_size=2)
    document.edit_line(1, "B2")
    assert document.cards[0] == "A\nB2"
    assert document.add_line("D", 2) == 2
    assert document.cards == ["A\nB2", "D\nC"]
    assert document.move_line(2, 1) == 1
    assert document.lines == ["A", "D", "B2", "C"]
    assert document.delete_line(2) == "B2"
    assert document.lines == ["A", "D", "C"]
    assert document.is_modified


def test_blank_source_edit_is_rejected() -> None:
    document = SubtitleDocument(lines=["A"])
    with pytest.raises(ValueError):
        document.edit_line(0, "  ")


def test_save_round_trip_is_utf8_without_bom_and_atomic(tmp_path: Path) -> None:
    path = tmp_path / "service.txt"
    document = SubtitleDocument(lines=["첫 줄", "둘째 줄"], group_size=2, is_modified=True)
    saved = save_subtitle(document, path)
    assert saved == path.resolve()
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert path.read_text(encoding="utf-8") == "첫 줄\n둘째 줄\n"
    assert load_subtitle(path, 1).lines == document.lines
    assert document.is_modified is False
    assert not (tmp_path / ".service.txt.tmp").exists()
