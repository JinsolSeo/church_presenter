from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from importlib.resources import files
from itertools import pairwise
from pathlib import Path

from church_presenter.domain.bible import (
    BibleBook,
    BibleChapter,
    BibleDocument,
    BiblePassageRange,
    BibleReference,
    BibleTranslation,
    BibleVerse,
)
from church_presenter.services.json_io import read_json_object


@dataclass(frozen=True, slots=True)
class BookSpec:
    id: str
    name: str
    chapter_count: int


BOOK_SPECS = (
    BookSpec("GEN", "창세기", 50),
    BookSpec("EXO", "출애굽기", 40),
    BookSpec("LEV", "레위기", 27),
    BookSpec("NUM", "민수기", 36),
    BookSpec("DEU", "신명기", 34),
    BookSpec("JOS", "여호수아기", 24),
    BookSpec("JDG", "사사기", 21),
    BookSpec("RUT", "룻기", 4),
    BookSpec("1SA", "사무엘기상", 31),
    BookSpec("2SA", "사무엘기하", 24),
    BookSpec("1KI", "열왕기상", 22),
    BookSpec("2KI", "열왕기하", 25),
    BookSpec("1CH", "역대기상", 29),
    BookSpec("2CH", "역대기하", 36),
    BookSpec("EZR", "에스라", 10),
    BookSpec("NEH", "느헤미야", 13),
    BookSpec("EST", "에스더", 10),
    BookSpec("JOB", "욥기", 42),
    BookSpec("PSA", "시편", 150),
    BookSpec("PRO", "잠언", 31),
    BookSpec("ECC", "전도서", 12),
    BookSpec("SNG", "아가", 8),
    BookSpec("ISA", "이사야", 66),
    BookSpec("JER", "예레미야", 52),
    BookSpec("LAM", "예레미야애가", 5),
    BookSpec("EZK", "에스겔", 48),
    BookSpec("DAN", "다니엘", 12),
    BookSpec("HOS", "호세아", 14),
    BookSpec("JOL", "요엘", 3),
    BookSpec("AMO", "아모스", 9),
    BookSpec("OBA", "오바댜", 1),
    BookSpec("JON", "요나", 4),
    BookSpec("MIC", "미가", 7),
    BookSpec("NAM", "나훔", 3),
    BookSpec("HAB", "하박국", 3),
    BookSpec("ZEP", "스바냐", 3),
    BookSpec("HAG", "학개", 2),
    BookSpec("ZEC", "스가랴", 14),
    BookSpec("MAL", "말라기", 4),
    BookSpec("MAT", "마태복음", 28),
    BookSpec("MRK", "마가복음", 16),
    BookSpec("LUK", "누가복음", 24),
    BookSpec("JHN", "요한복음", 21),
    BookSpec("ACT", "사도행전", 28),
    BookSpec("ROM", "로마서", 16),
    BookSpec("1CO", "고린도전서", 16),
    BookSpec("2CO", "고린도후서", 13),
    BookSpec("GAL", "갈라디아서", 6),
    BookSpec("EPH", "에베소서", 6),
    BookSpec("PHP", "빌립보서", 4),
    BookSpec("COL", "골로새서", 4),
    BookSpec("1TH", "데살로니가전서", 5),
    BookSpec("2TH", "데살로니가후서", 3),
    BookSpec("1TI", "디모데전서", 6),
    BookSpec("2TI", "디모데후서", 4),
    BookSpec("TIT", "디도서", 3),
    BookSpec("PHM", "빌레몬서", 1),
    BookSpec("HEB", "히브리서", 13),
    BookSpec("JAS", "야고보서", 5),
    BookSpec("1PE", "베드로전서", 5),
    BookSpec("2PE", "베드로후서", 3),
    BookSpec("1JN", "요한일서", 5),
    BookSpec("2JN", "요한이서", 1),
    BookSpec("3JN", "요한삼서", 1),
    BookSpec("JUD", "유다서", 1),
    BookSpec("REV", "요한계시록", 22),
)

_RANGE_PREFIX = re.compile(r"^(\d+)(?:\s*[\u2013-]\s*(\d+))?\s+(.+)$", re.DOTALL)
_TITLE_CONTINUATION_SPANS = {
    ("창세기", 8, 19): "c2f8e28f93acac6241e0cec1659896078366bfb00119c52be6e09b5ae1f34f76",
    ("에스겔", 16, 34): "0052375895f6f12833cc75a8ff9383036996b763802caf016ce15bba316dae30",
}
_SPEAKER_LABEL = re.compile(r"^\([^()]+\)$")


@dataclass(frozen=True, slots=True)
class BibleImportReport:
    source_path: Path
    source_verse_spans: int
    continuation_spans: int
    excluded_titles: int
    combined_ranges: int
    chapter_count: int
    output_unit_count: int
    covered_verse_count: int


@dataclass(slots=True)
class _RawSpan:
    kind: str
    number_text: str
    text: str


@dataclass(slots=True)
class _SourceBlock:
    source_book: str
    source_chapter: int
    spans: list[_RawSpan]


@dataclass(slots=True)
class _MutableUnit:
    number: int
    end_number: int | None
    text: str

    @property
    def last_number(self) -> int:
        return self.end_number or self.number


class _BibleHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.div_depth = 0
        self.book_depth: int | None = None
        self.chapter_depth: int | None = None
        self.current_book: str | None = None
        self.current_block: _SourceBlock | None = None
        self.blocks: list[_SourceBlock] = []
        self.capture_kind: str | None = None
        self.capture_text: list[str] = []
        self.capture_number: list[str] = []
        self.in_verse_number = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {key: value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        if tag == "div":
            self.div_depth += 1
            element_id = attributes.get("id", "")
            if "book" in classes and element_id.startswith("book-"):
                self.current_book = element_id.removeprefix("book-")
                self.book_depth = self.div_depth
            if "chapter" in classes and element_id.startswith("chap-"):
                if self.current_book is None:
                    raise ValueError("chapter appeared outside a book")
                try:
                    chapter = int(element_id.rsplit("-", 1)[1])
                except ValueError as error:
                    raise ValueError(f"invalid chapter id {element_id!r}") from error
                self.current_block = _SourceBlock(self.current_book, chapter, [])
                self.blocks.append(self.current_block)
                self.chapter_depth = self.div_depth
        elif tag == "span" and ({"verse", "cont"} & classes):
            self.capture_kind = "verse" if "verse" in classes else "cont"
            self.capture_text = []
            self.capture_number = []
        elif tag == "sup" and self.capture_kind == "verse":
            self.in_verse_number = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "sup":
            self.in_verse_number = False
        elif tag == "span" and self.capture_kind is not None:
            if self.current_block is None:
                raise ValueError("verse appeared outside a chapter")
            self.current_block.spans.append(
                _RawSpan(
                    self.capture_kind,
                    "".join(self.capture_number).strip(),
                    " ".join("".join(self.capture_text).split()),
                )
            )
            self.capture_kind = None
            self.capture_text = []
            self.capture_number = []
        elif tag == "div":
            if self.chapter_depth == self.div_depth:
                self.current_block = None
                self.chapter_depth = None
            if self.book_depth == self.div_depth:
                self.current_book = None
                self.book_depth = None
            self.div_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.capture_kind is None:
            return
        if self.in_verse_number:
            self.capture_number.append(data)
        else:
            self.capture_text.append(data)


def convert_logos_bible_html(path: Path) -> tuple[BibleDocument, BibleImportReport]:
    """Convert the supplied Logos-derived HTML using audited structural repairs."""
    source = path.expanduser().resolve()
    parser = _BibleHtmlParser()
    parser.feed(source.read_text(encoding="utf-8"))

    segments_by_source: dict[str, list[tuple[BibleVerse, ...]]] = {}
    excluded_titles = 0
    combined_ranges = 0
    for block in parser.blocks:
        segments, block_titles, block_ranges = _segments_from_block(
            block,
            excluded_continuation_indexes=_excluded_title_indexes(block),
        )
        segments_by_source.setdefault(block.source_book, []).extend(segments)
        excluded_titles += block_titles
        combined_ranges += block_ranges

    chapters_by_name = _repair_source_fragments(segments_by_source)
    books: list[BibleBook] = []
    for order, spec in enumerate(BOOK_SPECS, start=1):
        chapter_rows = chapters_by_name.get(spec.name, [])
        if len(chapter_rows) != spec.chapter_count:
            raise ValueError(
                f"{spec.name} expected {spec.chapter_count} chapters, got {len(chapter_rows)}"
            )
        books.append(
            BibleBook(
                id=spec.id,
                name=spec.name,
                order=order,
                chapters=tuple(
                    BibleChapter(number=index, verses=verses)
                    for index, verses in enumerate(chapter_rows, start=1)
                ),
            )
        )

    document = BibleDocument(
        translation=BibleTranslation(
            id="new_korean_translation",
            name="성경전서 새번역",
            revision="2001 electronic edition",
        ),
        books=tuple(books),
    )
    report = BibleImportReport(
        source_path=source,
        source_verse_spans=sum(
            span.kind == "verse" for block in parser.blocks for span in block.spans
        ),
        continuation_spans=sum(
            span.kind == "cont" for block in parser.blocks for span in block.spans
        ),
        excluded_titles=excluded_titles,
        combined_ranges=combined_ranges,
        chapter_count=document.chapter_count,
        output_unit_count=document.output_unit_count,
        covered_verse_count=document.covered_verse_count,
    )
    return document, report


def _excluded_title_indexes(block: _SourceBlock) -> frozenset[int]:
    indexes: set[int] = set()
    for (book, chapter, index), expected_hash in _TITLE_CONTINUATION_SPANS.items():
        if (block.source_book, block.source_chapter) != (book, chapter):
            continue
        if index >= len(block.spans):
            raise ValueError(f"{book} {chapter}: expected title span {index} is missing")
        span = block.spans[index]
        actual_hash = hashlib.sha256(span.text.encode("utf-8")).hexdigest()
        if span.kind != "cont" or actual_hash != expected_hash:
            raise ValueError(f"{book} {chapter}: audited title span {index} changed")
        indexes.add(index)
    return frozenset(indexes)


def _segments_from_block(
    block: _SourceBlock,
    *,
    excluded_continuation_indexes: frozenset[int] = frozenset(),
) -> tuple[list[tuple[BibleVerse, ...]], int, int]:
    units: list[_MutableUnit] = []
    excluded_titles = 0
    combined_ranges = 0
    for span_index, span in enumerate(block.spans):
        if span.kind == "verse":
            if not span.number_text.isdigit():
                raise ValueError(
                    f"{block.source_book} {block.source_chapter}: invalid verse number "
                    f"{span.number_text!r}"
                )
            units.append(_MutableUnit(int(span.number_text), None, span.text))
            continue

        match = _RANGE_PREFIX.match(span.text)
        if match is not None:
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) is not None else None
            units.append(_MutableUnit(start, end, match.group(3)))
            if end is not None:
                combined_ranges += 1
            continue
        if span_index in excluded_continuation_indexes or _SPEAKER_LABEL.fullmatch(span.text):
            excluded_titles += 1
            continue
        if not units:
            raise ValueError(
                f"{block.source_book} {block.source_chapter}: continuation before verse"
            )
        units[-1].text = f"{units[-1].text} {span.text}".strip()

    if not units:
        return [], excluded_titles, combined_ranges

    boundaries = {0}
    for index in range(1, len(units)):
        unit = units[index]
        following_start = units[index + 1].number if index + 1 < len(units) else None
        if unit.number == 1 or (unit.number != 2 and following_start == 2):
            boundaries.add(index)
    for index in range(1, len(units)):
        unit = units[index]
        previous = units[index - 1]
        is_second_unit_of_segment = index - 1 in boundaries and unit.number == 2
        if unit.number <= previous.last_number and not is_second_unit_of_segment:
            boundaries.add(index)

    starts = sorted(boundaries)
    starts.append(len(units))
    segments: list[tuple[BibleVerse, ...]] = []
    for start, stop in pairwise(starts):
        rows = units[start:stop]
        rows[0].number = 1
        rows[0].end_number = None
        verses = tuple(BibleVerse(row.number, row.text, row.end_number) for row in rows)
        segments.append(verses)
    return segments, excluded_titles, combined_ranges


def _repair_source_fragments(
    source: dict[str, list[tuple[BibleVerse, ...]]],
) -> dict[str, list[tuple[BibleVerse, ...]]]:
    """Repair four known book-boundary errors in the supplied exported HTML."""
    repaired = {name: list(rows) for name, rows in source.items()}
    jeremiah = repaired.get("예레미야", [])
    mislabeled_lamentations = repaired.get("예레미야애가", [])
    ezekiel_start = repaired.get("에스겔", [])
    amos_start = repaired.get("아모스", [])
    if not (
        len(jeremiah) == 57
        and len(mislabeled_lamentations) == 35
        and len(ezekiel_start) == 18
        and len(amos_start) == 4
    ):
        raise ValueError(
            "source does not match the audited Logos export repair signature: "
            f"Jer={len(jeremiah)}, Lam={len(mislabeled_lamentations)}, "
            f"Ezek={len(ezekiel_start)}, Amos={len(amos_start)}"
        )
    repaired["예레미야"] = jeremiah[:52]
    repaired["예레미야애가"] = jeremiah[52:]
    repaired["에스겔"] = ezekiel_start + mislabeled_lamentations[:30]
    repaired["아모스"] = amos_start + mislabeled_lamentations[30:]
    return repaired


class BibleRepository:
    """Validated in-memory lookup for a canonical Bible JSON document."""

    def __init__(self, document: BibleDocument) -> None:
        self.document = document
        self._books = {book.id: book for book in document.books}
        self._chapters = {
            (book.id, chapter.number): chapter
            for book in document.books
            for chapter in book.chapters
        }

    @classmethod
    def load(cls, path: Path) -> BibleRepository:
        return cls(BibleDocument.from_dict(read_json_object(path)))

    @classmethod
    def load_bundled(cls) -> BibleRepository:
        """Load the validated default translation from the installed package."""
        resource = files("church_presenter.assets.bibles").joinpath("new_korean_translation.json")
        payload = json.loads(resource.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("bundled Bible JSON root must be an object")
        return cls(BibleDocument.from_dict(payload))

    @property
    def books(self) -> tuple[BibleBook, ...]:
        return self.document.books

    def book(self, book_id: str) -> BibleBook:
        try:
            return self._books[book_id]
        except KeyError as error:
            raise KeyError(f"unknown Bible book {book_id!r}") from error

    def chapter(self, book_id: str, chapter: int) -> BibleChapter:
        try:
            return self._chapters[(book_id, chapter)]
        except KeyError as error:
            raise KeyError(f"unknown Bible chapter {book_id}.{chapter}") from error

    def verse(self, book_id: str, chapter: int, verse: int) -> BibleVerse:
        for row in self.chapter(book_id, chapter).verses:
            if row.number <= verse <= row.last_number:
                return row
        raise KeyError(f"unknown Bible verse {book_id}.{chapter}.{verse}")

    def passage(
        self,
        passage_range: BiblePassageRange,
    ) -> tuple[tuple[BibleReference, BibleVerse], ...]:
        """Flatten one inclusive range without materializing unrelated chapters."""
        rows: list[tuple[BibleReference, BibleVerse]] = []
        book_id = passage_range.start.book_id
        for chapter_number in range(
            passage_range.start.chapter,
            passage_range.end.chapter + 1,
        ):
            chapter = self.chapter(book_id, chapter_number)
            for verse in chapter.verses:
                if chapter_number == passage_range.start.chapter and (
                    verse.last_number < passage_range.start.verse
                ):
                    continue
                if chapter_number == passage_range.end.chapter and (
                    verse.number > passage_range.end.verse
                ):
                    continue
                rows.append((BibleReference(book_id, chapter_number, verse.number), verse))
        if not rows:
            raise ValueError("Bible range does not contain any available verses")
        return tuple(rows)
