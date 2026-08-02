from __future__ import annotations

import argparse
from pathlib import Path

from church_presenter.services.bible_service import convert_logos_bible_html
from church_presenter.services.json_io import atomic_write_json


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert the audited Logos Bible HTML export to canonical JSON."
    )
    parser.add_argument("source", type=Path, help="source self-contained HTML file")
    parser.add_argument("destination", type=Path, help="destination JSON file")
    args = parser.parse_args()

    document, report = convert_logos_bible_html(args.source)
    atomic_write_json(args.destination, document.to_dict())
    print(f"source verse spans: {report.source_verse_spans}")
    print(f"continuation spans: {report.continuation_spans}")
    print(f"excluded titles: {report.excluded_titles}")
    print(f"combined verse ranges: {report.combined_ranges}")
    print(f"books: {len(document.books)}")
    print(f"chapters: {report.chapter_count}")
    print(f"output units: {report.output_unit_count}")
    print(f"covered verse numbers: {report.covered_verse_count}")
    print(f"wrote: {args.destination.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
