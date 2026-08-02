from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class BibleVerse:
    """One selectable output unit, optionally spanning inseparable source verses."""

    number: int
    text: str
    end_number: int | None = None

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("verse number must be positive")
        if self.end_number is not None and self.end_number <= self.number:
            raise ValueError("end_number must be greater than number")
        cleaned = " ".join(self.text.split())
        if not cleaned:
            raise ValueError("verse text cannot be blank")
        if cleaned != self.text:
            object.__setattr__(self, "text", cleaned)

    @property
    def last_number(self) -> int:
        return self.end_number or self.number

    @property
    def number_label(self) -> str:
        if self.end_number is None:
            return str(self.number)
        return f"{self.number}\N{EN DASH}{self.end_number}"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"number": self.number, "text": self.text}
        if self.end_number is not None:
            payload["end_number"] = self.end_number
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BibleVerse:
        return cls(
            number=_required_int(data.get("number"), "verse number"),
            end_number=_optional_int(data.get("end_number"), "verse end_number"),
            text=str(data.get("text", "")),
        )


@dataclass(frozen=True, slots=True)
class BibleChapter:
    number: int
    verses: tuple[BibleVerse, ...]

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("chapter number must be positive")
        if not self.verses:
            raise ValueError("chapter must contain at least one verse")
        previous = 0
        for verse in self.verses:
            if verse.number <= previous:
                raise ValueError(f"chapter {self.number} verse numbers must be strictly increasing")
            previous = verse.last_number
        if self.verses[0].number != 1:
            raise ValueError(f"chapter {self.number} must begin with verse 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "verses": [verse.to_dict() for verse in self.verses],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BibleChapter:
        rows = data.get("verses")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise TypeError("chapter verses must be a list of objects")
        return cls(
            number=_required_int(data.get("number"), "chapter number"),
            verses=tuple(BibleVerse.from_dict(row) for row in rows),
        )


@dataclass(frozen=True, slots=True)
class BibleBook:
    id: str
    name: str
    order: int
    chapters: tuple[BibleChapter, ...]

    def __post_init__(self) -> None:
        if not self.id or not self.id.isascii() or self.id.upper() != self.id:
            raise ValueError("book id must be a non-empty uppercase ASCII identifier")
        if not self.name.strip():
            raise ValueError("book name cannot be blank")
        if self.order < 1:
            raise ValueError("book order must be positive")
        expected = tuple(range(1, len(self.chapters) + 1))
        actual = tuple(chapter.number for chapter in self.chapters)
        if actual != expected:
            raise ValueError(f"book {self.id} chapters must be sequential from 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "order": self.order,
            "chapters": [chapter.to_dict() for chapter in self.chapters],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BibleBook:
        rows = data.get("chapters")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise TypeError("book chapters must be a list of objects")
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            order=_required_int(data.get("order"), "book order"),
            chapters=tuple(BibleChapter.from_dict(row) for row in rows),
        )


@dataclass(frozen=True, slots=True)
class BibleTranslation:
    id: str
    name: str
    revision: str

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise ValueError("translation id and name cannot be blank")

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "revision": self.revision}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BibleTranslation:
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            revision=str(data.get("revision", "")),
        )


@dataclass(frozen=True, slots=True)
class BibleDocument:
    translation: BibleTranslation
    books: tuple[BibleBook, ...]
    schema_version: int = 1

    DOCUMENT_TYPE = "church_presenter_bible"

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("only Bible schema version 1 can be created")
        if len(self.books) != 66:
            raise ValueError("Bible document must contain 66 books")
        orders = tuple(book.order for book in self.books)
        if orders != tuple(range(1, 67)):
            raise ValueError("Bible book order must be sequential from 1")
        ids = [book.id for book in self.books]
        if len(ids) != len(set(ids)):
            raise ValueError("Bible book ids must be unique")

    @property
    def chapter_count(self) -> int:
        return sum(len(book.chapters) for book in self.books)

    @property
    def output_unit_count(self) -> int:
        return sum(len(chapter.verses) for book in self.books for chapter in book.chapters)

    @property
    def covered_verse_count(self) -> int:
        return sum(
            verse.last_number - verse.number + 1
            for book in self.books
            for chapter in book.chapters
            for verse in chapter.verses
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "document_type": self.DOCUMENT_TYPE,
            "translation": self.translation.to_dict(),
            "books": [book.to_dict() for book in self.books],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BibleDocument:
        if data.get("document_type") != cls.DOCUMENT_TYPE:
            raise ValueError(f"expected document_type {cls.DOCUMENT_TYPE!r}")
        version = _required_int(data.get("schema_version"), "schema_version")
        translation = data.get("translation")
        books = data.get("books")
        if not isinstance(translation, dict):
            raise TypeError("translation must be an object")
        if not isinstance(books, list) or not all(isinstance(row, dict) for row in books):
            raise TypeError("books must be a list of objects")
        return cls(
            schema_version=version,
            translation=BibleTranslation.from_dict(translation),
            books=tuple(BibleBook.from_dict(row) for row in books),
        )


@dataclass(frozen=True, slots=True)
class BibleReference:
    book_id: str
    chapter: int
    verse: int

    def __post_init__(self) -> None:
        if not self.book_id or self.chapter < 1 or self.verse < 1:
            raise ValueError("Bible reference values must be positive")

    @property
    def key(self) -> str:
        return f"{self.book_id}.{self.chapter}.{self.verse}"

    @classmethod
    def parse(cls, value: str) -> BibleReference:
        parts = value.split(".")
        if len(parts) != 3:
            raise ValueError(f"invalid Bible reference {value!r}")
        return cls(parts[0], int(parts[1]), int(parts[2].split("-", 1)[0]))


@dataclass(frozen=True, slots=True)
class BiblePassageRange:
    start: BibleReference
    end: BibleReference

    def __post_init__(self) -> None:
        if self.start.book_id != self.end.book_id:
            raise ValueError("a Bible range cannot cross book boundaries")
        if (self.end.chapter, self.end.verse) < (self.start.chapter, self.start.verse):
            raise ValueError("Bible range end must not precede its start")

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start.key, "end": self.end.key}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BiblePassageRange:
        return cls(
            BibleReference.parse(str(data.get("start", ""))),
            BibleReference.parse(str(data.get("end", ""))),
        )


def _required_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _optional_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    return _required_int(value, label)
