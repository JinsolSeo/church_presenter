from __future__ import annotations

from pathlib import Path

from church_presenter.media.youtube_resolver import validate_youtube_url
from church_presenter.services.json_io import atomic_write_json, read_json_object

VIDEO_URL_FILENAME = "video_url.json"
VIDEO_URL_SCHEMA_VERSION = 1


class VideoUrlService:
    """Persist folder-scoped YouTube video URLs under one fixed filename."""

    def load(self, folder: Path) -> list[str]:
        source = folder.expanduser().resolve() / VIDEO_URL_FILENAME
        if not source.is_file():
            return []
        payload = read_json_object(source)
        version = payload.get("version")
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or version != VIDEO_URL_SCHEMA_VERSION
        ):
            raise ValueError("지원하지 않는 video_url.json 버전입니다.")
        rows = payload.get("urls")
        if not isinstance(rows, list):
            raise TypeError("video_url.json urls는 목록이어야 합니다.")
        urls: list[str] = []
        seen: set[str] = set()
        for row in rows:
            raw = row.get("url") if isinstance(row, dict) else row
            if not isinstance(raw, str):
                raise TypeError("video_url.json URL 항목이 올바르지 않습니다.")
            url = validate_youtube_url(raw)
            if url not in seen:
                seen.add(url)
                urls.append(url)
        return urls

    def save(self, folder: Path, urls: list[str]) -> Path:
        destination = folder.expanduser().resolve() / VIDEO_URL_FILENAME
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in urls:
            url = validate_youtube_url(raw)
            if url not in seen:
                seen.add(url)
                normalized.append(url)
        atomic_write_json(
            destination,
            {
                "version": VIDEO_URL_SCHEMA_VERSION,
                "urls": [{"url": url} for url in normalized],
            },
        )
        return destination
