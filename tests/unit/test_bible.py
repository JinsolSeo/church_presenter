from __future__ import annotations

from pathlib import Path

import pytest

from church_presenter.domain.bible import BibleChapter, BibleVerse
from church_presenter.services.bible_service import (
    BibleRepository,
    _BibleHtmlParser,
    _segments_from_block,
)
from church_presenter.services.json_io import (
    atomic_write_json,
    read_json_object,
    require_schema_version,
)

BIBLE_PATH = (
    Path(__file__).parents[2]
    / "src"
    / "church_presenter"
    / "assets"
    / "bibles"
    / "new_korean_translation.json"
)
EN_DASH = "\N{EN DASH}"


def test_atomic_json_round_trip_and_cleans_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "document.json"

    atomic_write_json(path, {"한글": "보존", "value": 3})

    assert read_json_object(path) == {"한글": "보존", "value": 3}
    assert not path.with_name(f".{path.name}.tmp").exists()


def test_schema_version_validation_rejects_future_documents() -> None:
    payload = {"document_type": "example", "schema_version": 4}

    with pytest.raises(ValueError, match="unsupported schema_version 4"):
        require_schema_version(
            payload,
            document_type="example",
            supported_versions={1, 2, 3},
        )


def test_chapter_accepts_combined_ranges_and_intentional_number_gaps() -> None:
    chapter = BibleChapter(
        1,
        (
            BibleVerse(1, "첫 절"),
            BibleVerse(2, "둘째와 셋째 절", 3),
            BibleVerse(5, "원문에서 4절을 생략한 다음 절"),
        ),
    )

    assert [verse.number_label for verse in chapter.verses] == [
        "1",
        f"2{EN_DASH}3",
        "5",
    ]


def test_html_parser_excludes_titles_and_preserves_combined_ranges() -> None:
    parser = _BibleHtmlParser()
    parser.feed(
        """
        <div class="book" id="book-창세기">
          <div class="chapter" id="chap-창세기-16">
            <span class="verse"><sup class="vnum">16</sup>첫 장의 첫 절</span>
            <span class="verse"><sup class="vnum">2</sup>첫 장의 둘째 절</span>
            <span class="verse"><sup class="vnum">17</sup>다음 장의 첫 절</span>
            <span class="cont">2&#8211;3&nbsp; 합쳐진 둘째와 셋째 절</span>
            <div class="section-heading">표시하지 않을 제목</div>
            <span class="cont">제목으로 잘못 내보낸 연속 문단</span>
            <span class="verse"><sup class="vnum">4</sup>다음 장의 넷째 절</span>
          </div>
        </div>
        """
    )

    segments, excluded_titles, combined_ranges = _segments_from_block(
        parser.blocks[0], excluded_continuation_indexes=frozenset({4})
    )

    assert len(segments) == 2
    assert [verse.number_label for verse in segments[0]] == ["1", "2"]
    assert [verse.number_label for verse in segments[1]] == [
        "1",
        f"2{EN_DASH}3",
        "4",
    ]
    assert excluded_titles == 1
    assert combined_ranges == 1
    assert all("제목" not in verse.text for rows in segments for verse in rows)


def test_local_bible_asset_is_complete_and_lookup_ready() -> None:
    if not BIBLE_PATH.exists():
        pytest.skip("local licensed Bible asset is not present")
    repository = BibleRepository.load(BIBLE_PATH)
    document = repository.document

    assert len(document.books) == 66
    assert document.chapter_count == 1189
    assert document.output_unit_count == 31094
    assert document.covered_verse_count == 31101
    assert repository.verse("GEN", 2, 1).text
    assert repository.verse("JHN", 3, 16).text


def test_bundled_bible_asset_loads_through_package_resources() -> None:
    if not BIBLE_PATH.exists():
        pytest.skip("local licensed Bible asset is not present")
    repository = BibleRepository.load_bundled()

    assert repository.document.translation.id == "new_korean_translation"
    assert repository.book("GEN").name == "창세기"


def test_import_repairs_and_numbering_are_present_in_local_asset() -> None:
    if not BIBLE_PATH.exists():
        pytest.skip("local licensed Bible asset is not present")
    repository = BibleRepository.load(BIBLE_PATH)

    assert len(repository.book("LAM").chapters) == 5
    assert len(repository.book("EZK").chapters) == 48
    assert len(repository.book("AMO").chapters) == 9
    assert repository.verse("JER", 17, 2).number_label == f"2{EN_DASH}3"
    assert [verse.number for verse in repository.chapter("ACT", 24).verses][5:8] == [6, 8, 9]
