from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

LOGGER = logging.getLogger(__name__)
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


class YouTubeResolverError(RuntimeError):
    """A YouTube resolution failure with a safe operator-facing message."""


@dataclass(frozen=True, slots=True)
class YouTubeMetadata:
    title: str
    duration_ms: int | None
    video_id: str
    original_url: str

    def as_playlist_metadata(self) -> dict[str, str]:
        return {"video_id": self.video_id, "original_url": self.original_url}


@dataclass(frozen=True, slots=True)
class ResolvedYouTubeStream:
    stream_url: str
    metadata: YouTubeMetadata


def validate_youtube_url(url: str) -> str:
    """Validate a public single-video YouTube URL and return it stripped."""
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    host = parsed.netloc.casefold().split(":", maxsplit=1)[0]
    if parsed.scheme not in {"http", "https"} or host not in YOUTUBE_HOSTS:
        raise ValueError("지원하는 YouTube 영상 URL을 입력하십시오.")
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", maxsplit=1)[0]
    elif parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    else:
        video_id = ""
    if not video_id:
        raise ValueError("단일 YouTube 영상 URL만 지원합니다.")
    return cleaned


class YtDlpResolver:
    """Resolve metadata and ephemeral audio URLs without downloading files."""

    def __init__(self, *, socket_timeout: float = 12.0) -> None:
        self.socket_timeout = socket_timeout

    def metadata(self, url: str) -> YouTubeMetadata:
        info = self._extract(url)
        return self._metadata_from_info(info, url)

    def stream(self, url: str) -> ResolvedYouTubeStream:
        info = self._extract(url)
        stream_url = info.get("url")
        if not isinstance(stream_url, str) or not stream_url:
            requested = info.get("requested_downloads")
            if isinstance(requested, list) and requested and isinstance(requested[0], dict):
                stream_url = requested[0].get("url")
        if not isinstance(stream_url, str) or not stream_url:
            raise YouTubeResolverError("YouTube 오디오 스트림을 해석하지 못했습니다.")
        return ResolvedYouTubeStream(stream_url, self._metadata_from_info(info, url))

    def _extract(self, url: str) -> dict[str, Any]:
        cleaned = validate_youtube_url(url)
        try:
            module = importlib.import_module("yt_dlp")
        except (ImportError, OSError) as error:
            raise YouTubeResolverError(
                "yt-dlp가 설치되지 않아 YouTube 정보를 불러올 수 없습니다."
            ) from error
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "format": "bestaudio/best",
            "socket_timeout": self.socket_timeout,
            "retries": 1,
            "extractor_retries": 1,
        }
        try:
            with module.YoutubeDL(options) as ydl:
                info = ydl.extract_info(cleaned, download=False)
        except Exception as error:
            raise YouTubeResolverError(
                "YouTube 정보를 불러오지 못했습니다. 네트워크와 영상 공개 상태를 확인하십시오."
            ) from error
        if not isinstance(info, dict):
            raise YouTubeResolverError("YouTube 응답 형식이 올바르지 않습니다.")
        return info

    @staticmethod
    def _metadata_from_info(info: dict[str, Any], original_url: str) -> YouTubeMetadata:
        duration = info.get("duration")
        duration_ms = round(float(duration) * 1000) if isinstance(duration, (int, float)) else None
        video_id = str(info.get("id", ""))
        title = str(info.get("title") or video_id or "YouTube 항목")
        return YouTubeMetadata(title, duration_ms, video_id, original_url)


class _WorkerSignals(QObject):
    succeeded = Signal(str, object)
    failed = Signal(str, str)


class _ResolverTask(QRunnable):
    def __init__(
        self,
        request_id: str,
        resolver: YtDlpResolver,
        url: str,
        *,
        stream: bool,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.resolver = resolver
        self.url = url
        self.stream_mode = stream
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            result = (
                self.resolver.stream(self.url)
                if self.stream_mode
                else self.resolver.metadata(self.url)
            )
        except (ValueError, YouTubeResolverError) as error:
            LOGGER.exception("YouTube resolver request failed for %s", self.request_id)
            self.signals.failed.emit(self.request_id, str(error))
            return
        self.signals.succeeded.emit(self.request_id, result)


class YouTubeWorkerService(QObject):
    """Cancelable-generation facade for yt-dlp work on a private thread pool."""

    resolved = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, resolver: YtDlpResolver | None = None) -> None:
        super().__init__()
        self.resolver = resolver or YtDlpResolver()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self._pending: set[str] = set()
        self._closed = False

    def request_metadata(self, request_id: str, url: str) -> bool:
        return self._request(request_id, url, stream=False)

    def request_stream(self, request_id: str, url: str) -> bool:
        return self._request(request_id, url, stream=True)

    def cancel(self, request_id: str) -> None:
        self._pending.discard(request_id)

    def close(self) -> None:
        self._closed = True
        self._pending.clear()
        self.pool.clear()
        self.pool.waitForDone(1000)

    def _request(self, request_id: str, url: str, *, stream: bool) -> bool:
        if self._closed or request_id in self._pending:
            return False
        self._pending.add(request_id)
        task = _ResolverTask(request_id, self.resolver, url, stream=stream)
        task.signals.succeeded.connect(self._succeeded)
        task.signals.failed.connect(self._failed)
        self.pool.start(task)
        return True

    def _succeeded(self, request_id: str, result: object) -> None:
        if self._closed or request_id not in self._pending:
            return
        self._pending.remove(request_id)
        self.resolved.emit(request_id, result)

    def _failed(self, request_id: str, message: str) -> None:
        if self._closed or request_id not in self._pending:
            return
        self._pending.remove(request_id)
        self.failed.emit(request_id, message)
