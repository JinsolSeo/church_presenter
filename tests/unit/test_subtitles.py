from __future__ import annotations

from pathlib import Path

import pytest

from church_presenter.domain.models import SubtitleDocument
from church_presenter.services.subtitle_merge_service import (
    merge_subtitle_files,
    padding_count,
    save_merged_subtitle,
)
from church_presenter.services.subtitle_service import (
    load_subtitle,
    parse_subtitle_text,
    save_subtitle,
)


def test_parse_one_source_per_line_preserves_intentional_blanks() -> None:
    assert parse_subtitle_text(" first sentence. Second?\n\n 셋째 줄 \r\n") == [
        "first sentence. Second?",
        "",
        "셋째 줄",
    ]
    assert parse_subtitle_text("첫 줄\n") == ["첫 줄"]
    assert parse_subtitle_text("첫 줄\n\n") == ["첫 줄", ""]


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


def test_blank_source_edit_and_add_are_allowed() -> None:
    document = SubtitleDocument(lines=["A"])
    document.edit_line(0, "  ")
    document.add_line("")
    assert document.lines == ["", ""]
    assert document.cards == ["\n"]
    assert document.is_modified


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


def test_save_round_trip_preserves_blank_source_lines(tmp_path: Path) -> None:
    path = tmp_path / "with_blanks.txt"
    document = SubtitleDocument(lines=["첫 줄", "", "셋째 줄", ""], is_modified=True)

    save_subtitle(document, path)

    assert path.read_text(encoding="utf-8") == "첫 줄\n\n셋째 줄\n\n"
    assert load_subtitle(path).lines == ["첫 줄", "", "셋째 줄", ""]


@pytest.mark.parametrize(
    ("line_count", "group_size", "expected"),
    [(5, 2, 1), (6, 2, 0), (4, 3, 2), (5, 3, 1), (6, 3, 0)],
)
def test_merge_padding_count(
    line_count: int,
    group_size: int,
    expected: int,
) -> None:
    assert padding_count(line_count, group_size) == expected


def test_merge_files_pads_boundaries_but_not_the_last_file(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    third = tmp_path / "third.txt"
    first.write_text("A1\nA2\nA3\n", encoding="utf-8")
    second.write_text("B1\nB2\n", encoding="utf-8")
    third.write_text("C1\nC2\nC3\n", encoding="utf-8")

    document = merge_subtitle_files([first, second, third], group_size=2)

    assert document.lines == ["A1", "A2", "A3", "", "B1", "B2", "C1", "C2", "C3"]
    assert document.cards == ["A1\nA2", "A3\n", "B1\nB2", "C1\nC2", "C3"]


def test_save_merged_subtitle_rejects_overwriting_a_source(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("A\n", encoding="utf-8")

    with pytest.raises(ValueError, match="원본 자막 파일"):
        save_merged_subtitle([source], source, group_size=2)
