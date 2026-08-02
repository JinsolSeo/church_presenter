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
    http_headers: tuple[tuple[str, str], ...] = ()
    http_chunk_size: int | None = None
    protocol: str = ""
    audio_codec: str = ""


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
        return self._stream_from_info(info, url, "오디오")

    def video_stream(self, url: str) -> ResolvedYouTubeStream:
        """Resolve one progressive stream containing both video and audio."""
        info = self._extract_video(url)
        return self._stream_from_info(info, url, "영상")

    def _stream_from_info(
        self,
        info: dict[str, Any],
        url: str,
        media_label: str,
    ) -> ResolvedYouTubeStream:
        stream_url = info.get("url")
        selected = info
        if not isinstance(stream_url, str) or not stream_url:
            requested = info.get("requested_downloads")
            if isinstance(requested, list) and requested and isinstance(requested[0], dict):
                selected = requested[0]
                stream_url = selected.get("url")
        if not isinstance(stream_url, str) or not stream_url:
            raise YouTubeResolverError(f"YouTube {media_label} 스트림을 해석하지 못했습니다.")
        headers = self._http_headers(selected.get("http_headers") or info.get("http_headers"))
        downloader_options = selected.get("downloader_options") or info.get(
            "downloader_options"
        )
        chunk_size: int | None = None
        if isinstance(downloader_options, dict):
            raw_chunk_size = downloader_options.get("http_chunk_size")
            if isinstance(raw_chunk_size, int) and raw_chunk_size > 0:
                chunk_size = raw_chunk_size
        protocol = selected.get("protocol")
        audio_codec = selected.get("acodec")
        return ResolvedYouTubeStream(
            stream_url,
            self._metadata_from_info(info, url),
            http_headers=headers,
            http_chunk_size=chunk_size,
            protocol=protocol if isinstance(protocol, str) else "",
            audio_codec=audio_codec if isinstance(audio_codec, str) else "",
        )

    def _extract(self, url: str) -> dict[str, Any]:
        return self._extract_with_format(url, "bestaudio/best")

    def _extract_video(self, url: str) -> dict[str, Any]:
        return self._extract_with_format(
            url,
            (
                "best[protocol^=http][vcodec!=none][acodec!=none][ext=mp4]/"
                "best[protocol^=http][vcodec!=none][acodec!=none]/"
                "best[vcodec!=none][acodec!=none]"
            ),
        )

    def _extract_with_format(self, url: str, format_selector: str) -> dict[str, Any]:
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
            "format": format_selector,
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
    def _http_headers(value: object) -> tuple[tuple[str, str], ...]:
        """Keep yt-dlp playback headers in memory while rejecting header injection."""
        if not isinstance(value, dict):
            return ()
        headers: list[tuple[str, str]] = []
        for key, header_value in value.items():
            if not isinstance(key, str) or not isinstance(header_value, str):
                continue
            cleaned_key = key.strip()
            cleaned_value = header_value.strip()
            if (
                not cleaned_key
                or not cleaned_value
                or "\r" in cleaned_key
                or "\n" in cleaned_key
                or "\r" in cleaned_value
                or "\n" in cleaned_value
            ):
                continue
            headers.append((cleaned_key, cleaned_value))
        return tuple(headers)

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
        mode: str,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.resolver = resolver
        self.url = url
        self.mode = mode
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            result: ResolvedYouTubeStream | YouTubeMetadata
            if self.mode == "video":
                result = self.resolver.video_stream(self.url)
            elif self.mode == "audio":
                result = self.resolver.stream(self.url)
            else:
                result = self.resolver.metadata(self.url)
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
        return self._request(request_id, url, mode="metadata")

    def request_stream(self, request_id: str, url: str) -> bool:
        return self._request(request_id, url, mode="audio")

    def request_video_stream(self, request_id: str, url: str) -> bool:
        return self._request(request_id, url, mode="video")

    def cancel(self, request_id: str) -> None:
        self._pending.discard(request_id)

    def close(self) -> None:
        self._closed = True
        self._pending.clear()
        self.pool.clear()
        self.pool.waitForDone(1000)

    def _request(self, request_id: str, url: str, *, mode: str) -> bool:
        if self._closed or request_id in self._pending:
            return False
        self._pending.add(request_id)
        task = _ResolverTask(request_id, self.resolver, url, mode=mode)
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
