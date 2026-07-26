from __future__ import annotations

import importlib
import logging
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from church_presenter.domain.enums import PlaybackStatus
from church_presenter.media.audio_backend import StreamingAudioBackend
from church_presenter.media.youtube_resolver import (
    ResolvedYouTubeStream,
    YouTubeWorkerService,
)

LOGGER = logging.getLogger(__name__)
BUFFERING_TIMEOUT_MS = 15_000
STREAM_PREPARE_TIMEOUT_MS = 30_000
MPV_POLL_INTERVAL_MS = 100
MPV_DLL_NAMES = ("mpv-2.dll", "libmpv-2.dll", "mpv-1.dll")
AudioDeviceResolver = Callable[[str], object | None]
_WINDOWS_DLL_DIRECTORY_HANDLES: list[object] = []


def _configure_windows_libmpv_search() -> tuple[Path, ...]:
    """Add trusted application libmpv directories before importing python-mpv."""
    if sys.platform != "win32":
        return ()
    roots: list[Path] = []
    configured = os.environ.get("CHURCH_PRESENTER_LIBMPV_DIR", "").strip()
    if configured:
        roots.append(Path(configured).expanduser())
    roots.extend(
        (
            Path(sys.executable).resolve().parent,
            Path(__file__).resolve().parent,
        )
    )
    frozen_root = getattr(sys, "_MEIPASS", "")
    if isinstance(frozen_root, str) and frozen_root:
        roots.append(Path(frozen_root))

    found: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        for candidate in (root, root / "libmpv", root / "mpv"):
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved in seen or not resolved.is_dir():
                continue
            seen.add(resolved)
            if not any((resolved / name).is_file() for name in MPV_DLL_NAMES):
                continue
            found.append(resolved)

    if not found:
        return ()
    current_path = os.environ.get("PATH", "")
    current_entries = {
        Path(entry).resolve()
        for entry in current_path.split(os.pathsep)
        if entry
    }
    additions = [str(path) for path in found if path not in current_entries]
    if additions:
        os.environ["PATH"] = os.pathsep.join((*additions, current_path))
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if callable(add_dll_directory):
        for path in found:
            try:
                _WINDOWS_DLL_DIRECTORY_HANDLES.append(add_dll_directory(str(path)))
            except OSError:
                LOGGER.exception("Could not add bundled libmpv DLL directory: %s", path)
    LOGGER.info("Configured bundled libmpv search directories: %s", found)
    return tuple(found)


class _MpvInitSignals(QObject):
    succeeded = Signal(str, object)
    failed = Signal(str, str)


class _MpvInitTask(QRunnable):
    def __init__(self, request_id: str) -> None:
        super().__init__()
        self.request_id = request_id
        self.signals = _MpvInitSignals()

    def run(self) -> None:
        try:
            bundled_directories = _configure_windows_libmpv_search()
            module = importlib.import_module("mpv")
            options: dict[str, object] = {
                "video": False,
                "ytdl": False,
                "terminal": False,
                "network_timeout": 15,
                "input_default_bindings": False,
                "input_vo_keyboard": False,
            }
            if sys.platform == "darwin":
                options.update(
                    {
                        "macos_app_activation_policy": "prohibited",
                        "macos_menu_shortcuts": False,
                        "input_media_keys": False,
                    }
                )
            player = module.MPV(**options)
            LOGGER.info(
                "libmpv initialized: platform=%s python_bits=%d bundled_dirs=%d",
                sys.platform,
                64 if sys.maxsize > 2**32 else 32,
                len(bundled_directories),
            )
        except (ImportError, OSError) as error:
            LOGGER.exception("libmpv could not be loaded")
            detail = (
                f"Windows용 mpv-2.dll을 찾거나 불러오지 못했습니다 "
                f"({64 if sys.maxsize > 2**32 else 32}비트)."
                if sys.platform == "win32"
                else "libmpv runtime을 불러오지 못했습니다."
            )
            self.signals.failed.emit(
                self.request_id,
                f"{detail} 설치 상태를 확인하십시오.",
            )
            LOGGER.error("libmpv load detail: %s", error)
            return
        except Exception:
            LOGGER.exception("libmpv initialization failed")
            self.signals.failed.emit(
                self.request_id,
                "YouTube 오디오 재생기를 초기화하지 못했습니다.",
            )
            return
        self.signals.succeeded.emit(self.request_id, player)


class MpvAudioBackend(StreamingAudioBackend):
    """Audio-only libmpv backend fed by ephemeral yt-dlp stream URLs."""

    buffering_sample = Signal(str, float)
    file_loaded_observed = Signal(str)
    eof_observed = Signal(str)
    stream_error_observed = Signal(str, str)

    def __init__(
        self,
        worker: YouTubeWorkerService | None = None,
        *,
        audio_device_resolver: AudioDeviceResolver | None = None,
    ) -> None:
        super().__init__()
        self.worker = worker or YouTubeWorkerService()
        self._audio_device_resolver = audio_device_resolver
        self.worker.resolved.connect(self._stream_resolved)
        self.worker.failed.connect(self._stream_failed)
        self._init_pool = QThreadPool(self)
        self._init_pool.setMaxThreadCount(1)
        self._source = ""
        self._status = PlaybackStatus.UNLOADED
        self._request_id = ""
        self._stream_url = ""
        self._stream_headers: tuple[tuple[str, str], ...] = ()
        self._stream_http_chunk_size: int | None = None
        self._stream_protocol = ""
        self._stream_audio_codec = ""
        self._player: Any | None = None
        self._volume = 0.7
        self._muted = False
        self._audio_device_id = ""
        self._audio_device_description = ""
        self._audio_device_native_id = ""
        self._closed = False
        self._loaded_emitted = False
        self._ended_emitted = False
        self._last_position_ms = -1
        self._last_duration_ms = -1
        self._poll_ticks = 0
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(MPV_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_player)
        self._buffer_timer = QTimer(self)
        self._buffer_timer.setSingleShot(True)
        self._buffer_timer.setInterval(BUFFERING_TIMEOUT_MS)
        self._buffer_timer.timeout.connect(self._buffer_timeout)
        self._prepare_timer = QTimer(self)
        self._prepare_timer.setSingleShot(True)
        self._prepare_timer.setInterval(STREAM_PREPARE_TIMEOUT_MS)
        self._prepare_timer.timeout.connect(self._prepare_timeout)
        self.buffering_sample.connect(self._apply_buffering)
        self.file_loaded_observed.connect(self._file_loaded)
        self.eof_observed.connect(self._ended)
        self.stream_error_observed.connect(self._stream_interrupted)

    def load(self, source: str) -> None:
        if self._closed:
            return
        self.stop()
        self._source = source
        self._request_id = uuid4().hex
        self._loaded_emitted = False
        self._ended_emitted = False
        self._last_position_ms = -1
        self._last_duration_ms = -1
        self._poll_ticks = 0
        self._set_status(PlaybackStatus.PREPARING)
        self._prepare_timer.start()
        if not self.worker.request_stream(self._request_id, source):
            self._emit_error("YouTube 오디오 준비 요청을 시작하지 못했습니다.")

    def play(self) -> None:
        if self._player is None:
            self._emit_error("YouTube 오디오가 아직 준비되지 않았습니다.")
            return
        try:
            self._player.pause = False
            self._set_status(PlaybackStatus.PLAYING)
        except Exception:
            LOGGER.exception("libmpv play failed")
            self._emit_error("YouTube 오디오 재생을 시작하지 못했습니다.")

    def pause(self) -> None:
        if self._player is None:
            return
        try:
            self._player.pause = True
            self._set_status(PlaybackStatus.PAUSED)
        except Exception:
            LOGGER.exception("libmpv pause failed")
            self._emit_error("YouTube 오디오를 일시정지하지 못했습니다.")

    def stop(self) -> None:
        self._poll_timer.stop()
        self._prepare_timer.stop()
        self._buffer_timer.stop()
        if self._request_id:
            self.worker.cancel(self._request_id)
        self._request_id = ""
        self._stream_url = ""
        self._stream_headers = ()
        self._stream_http_chunk_size = None
        self._stream_protocol = ""
        self._stream_audio_codec = ""
        player, self._player = self._player, None
        if player is not None:
            try:
                player.terminate()
            except Exception:
                LOGGER.exception("libmpv termination failed")
        if self._status is not PlaybackStatus.UNLOADED:
            self._set_status(PlaybackStatus.STOPPED)
        self.position_changed.emit(0)

    def seek(self, position_ms: int) -> None:
        if self._player is None:
            return
        try:
            self._player.time_pos = max(0, position_ms) / 1000
        except Exception:
            LOGGER.exception("libmpv seek failed")
            self._emit_error("YouTube 오디오 탐색에 실패했습니다.")

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))
        self._apply_volume()

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        self._apply_volume()

    def set_audio_output_device(self, device_id: str) -> bool:
        self._audio_device_id = device_id
        self._audio_device_description = ""
        self._audio_device_native_id = ""
        if not device_id:
            if self._player is not None:
                self._apply_audio_output_device(self._player)
            return True
        if self._audio_device_resolver is None:
            return False
        device = self._audio_device_resolver(device_id)
        if device is None:
            return False
        is_null = getattr(device, "isNull", None)
        if callable(is_null) and is_null():
            return False
        description = getattr(device, "description", None)
        if callable(description):
            self._audio_device_description = str(description() or "")
        identifier = getattr(device, "id", None)
        if callable(identifier):
            raw_identifier = identifier()
            data = getattr(raw_identifier, "data", None)
            native_value = data() if callable(data) else raw_identifier
            if isinstance(native_value, bytes):
                self._audio_device_native_id = native_value.decode(
                    "utf-8",
                    errors="ignore",
                )
            else:
                self._audio_device_native_id = str(native_value or "")
        if self._player is not None:
            self._apply_audio_output_device(self._player)
        return True

    def close(self) -> None:
        self._closed = True
        self._prepare_timer.stop()
        self._buffer_timer.stop()
        self.stop()
        self.worker.close()
        self._init_pool.clear()
        self._init_pool.waitForDone(1000)
        self._source = ""
        self._status = PlaybackStatus.UNLOADED

    @property
    def status(self) -> PlaybackStatus:
        return self._status

    @property
    def source(self) -> str:
        return self._source

    def _stream_resolved(self, request_id: str, result: object) -> None:
        if (
            self._closed
            or request_id != self._request_id
            or not isinstance(result, ResolvedYouTubeStream)
        ):
            return
        self._set_status(PlaybackStatus.LOADING)
        self._stream_url = result.stream_url
        self._stream_headers = result.http_headers
        self._stream_http_chunk_size = result.http_chunk_size
        self._stream_protocol = result.protocol
        self._stream_audio_codec = result.audio_codec
        LOGGER.info(
            "YouTube audio stream resolved: protocol=%s codec=%s headers=%d chunk_size=%s",
            self._stream_protocol or "unknown",
            self._stream_audio_codec or "unknown",
            len(self._stream_headers),
            self._stream_http_chunk_size or "default",
        )
        task = _MpvInitTask(request_id)
        task.signals.succeeded.connect(self._mpv_initialized)
        task.signals.failed.connect(self._mpv_failed)
        self._init_pool.start(task)

    def _stream_failed(self, request_id: str, message: str) -> None:
        if self._closed or request_id != self._request_id:
            return
        self._emit_error(message)

    def _mpv_initialized(self, request_id: str, player: object) -> None:
        if self._closed or request_id != self._request_id:
            try:
                player.terminate()  # type: ignore[attr-defined]
            except Exception:
                LOGGER.exception("Could not dispose stale libmpv instance")
            return
        self._player = player
        mpv_player: Any = player
        try:
            mpv_player.observe_property(
                "time-pos",
                lambda name, value: self._time_position(request_id, name, value),
            )
            mpv_player.observe_property(
                "duration",
                lambda name, value: self._duration(request_id, name, value),
            )
            mpv_player.observe_property(
                "eof-reached",
                lambda name, value: self._eof_reached(request_id, name, value),
            )
            mpv_player.observe_property(
                "cache-buffering-state",
                lambda name, value: self._buffering(request_id, name, value),
            )
            mpv_player.register_event_callback(
                lambda event: self._mpv_event(request_id, event)
            )
            self._configure_stream_request(mpv_player)
            self._apply_audio_output_device(mpv_player)
            mpv_player.pause = True
            mpv_player.loadfile(self._stream_url, "replace")
        except Exception:
            LOGGER.exception("Could not configure libmpv stream")
            self._emit_error("YouTube 오디오 스트림을 준비하지 못했습니다.")
            return
        self._apply_volume()
        self._poll_timer.start()

    def _mpv_failed(self, request_id: str, message: str) -> None:
        if self._closed or request_id != self._request_id:
            return
        self._emit_error(message)

    def _time_position(self, request_id: str, _name: str, value: object) -> None:
        if (
            not self._closed
            and request_id == self._request_id
            and isinstance(value, (int, float))
        ):
            position_ms = max(0, round(float(value) * 1000))
            if position_ms != self._last_position_ms:
                self._last_position_ms = position_ms
                self.position_changed.emit(position_ms)

    def _duration(self, request_id: str, _name: str, value: object) -> None:
        if (
            not self._closed
            and request_id == self._request_id
            and isinstance(value, (int, float))
        ):
            duration_ms = max(0, round(float(value) * 1000))
            if duration_ms != self._last_duration_ms:
                self._last_duration_ms = duration_ms
                self.duration_changed.emit(duration_ms)

    def _eof_reached(
        self,
        request_id: str,
        _name: str,
        value: object,
    ) -> None:
        if self._closed or request_id != self._request_id or value is not True:
            return
        self.eof_observed.emit(request_id)

    def _buffering(
        self,
        request_id: str,
        _name: str,
        value: object,
    ) -> None:
        if (
            self._closed
            or request_id != self._request_id
            or not isinstance(value, (int, float))
        ):
            return
        self.buffering_sample.emit(request_id, float(value))

    def _apply_buffering(self, request_id: str, percent: float) -> None:
        if request_id != self._request_id:
            return
        if percent < 100 and self._status is PlaybackStatus.PLAYING:
            self._set_status(PlaybackStatus.BUFFERING)
            self._buffer_timer.start()
        elif percent >= 100 and self._status is PlaybackStatus.BUFFERING:
            self._buffer_timer.stop()
            self._set_status(PlaybackStatus.PLAYING)

    def _buffer_timeout(self) -> None:
        if self._status is PlaybackStatus.BUFFERING:
            self._emit_error("YouTube 스트림 버퍼링 시간이 초과되었습니다.")

    def _prepare_timeout(self) -> None:
        if self._status in {PlaybackStatus.PREPARING, PlaybackStatus.LOADING}:
            if self._request_id:
                self.worker.cancel(self._request_id)
            self._request_id = ""
            player, self._player = self._player, None
            if player is not None:
                try:
                    player.terminate()
                except Exception:
                    LOGGER.exception("Could not terminate timed-out libmpv player")
            self._emit_error(
                "YouTube 오디오를 30초 안에 준비하지 못했습니다. "
                "네트워크와 libmpv 설치 상태를 확인하십시오."
            )

    def _poll_player(self) -> None:
        """Mirror libmpv properties when native callbacks are unavailable.

        python-mpv's macOS event thread can fail to deliver property and
        file-loaded callbacks even though libmpv has prepared the media. The
        Qt-owned timer also makes transport progress independent of that
        platform-specific callback path.
        """
        player = self._player
        request_id = self._request_id
        if self._closed or player is None or not request_id:
            self._poll_timer.stop()
            return
        self._poll_ticks += 1
        try:
            duration = getattr(player, "duration", None)
            position = getattr(player, "time_pos", None)
            eof_reached = getattr(player, "eof_reached", None)
            buffering = getattr(player, "cache_buffering_state", None)
            path = getattr(player, "path", None)
            core_idle = getattr(player, "core_idle", None)
            idle_active = getattr(player, "idle_active", None)
        except Exception:
            LOGGER.debug("Could not poll libmpv properties", exc_info=True)
            return

        if isinstance(duration, (int, float)):
            duration_ms = max(0, round(float(duration) * 1000))
            if duration_ms != self._last_duration_ms:
                self._last_duration_ms = duration_ms
                self.duration_changed.emit(duration_ms)
        if isinstance(position, (int, float)):
            position_ms = max(0, round(float(position) * 1000))
            if position_ms != self._last_position_ms:
                self._last_position_ms = position_ms
                self.position_changed.emit(position_ms)
        if isinstance(buffering, (int, float)):
            self._apply_buffering(request_id, float(buffering))

        prepared = isinstance(duration, (int, float)) or (
            self._poll_ticks >= 2
            and bool(path)
            and core_idle is True
            and idle_active is False
        )
        if prepared:
            self._file_loaded(request_id)
        if eof_reached is True:
            self._ended(request_id)

    def _mpv_event(self, request_id: str, event: object) -> None:
        if self._closed or request_id != self._request_id:
            return
        try:
            payload = event.as_dict()  # type: ignore[attr-defined]
        except Exception:
            LOGGER.exception("Could not decode libmpv event")
            return
        if not isinstance(payload, dict):
            return
        if payload.get("event_id") == 8:
            self.file_loaded_observed.emit(request_id)
            return
        if payload.get("event_id") != 7:
            return
        details = payload.get("event")
        reason = details.get("reason") if isinstance(details, dict) else None
        nested_error = details.get("error", 0) if isinstance(details, dict) else 0
        error_code = payload.get("error", 0) or nested_error
        if error_code or reason in {4, "error"}:
            LOGGER.warning(
                "libmpv stream ended with error: reason=%s error=%s",
                reason,
                error_code,
            )
            self.stream_error_observed.emit(
                request_id,
                "YouTube 스트림 재생이 중단되었습니다.",
            )

    def _file_loaded(self, request_id: str) -> None:
        if (
            self._closed
            or request_id != self._request_id
            or self._player is None
            or self._loaded_emitted
        ):
            return
        self._prepare_timer.stop()
        self._set_status(PlaybackStatus.READY)
        self._loaded_emitted = True
        self.loaded.emit()

    def _ended(self, request_id: str) -> None:
        if (
            self._closed
            or request_id != self._request_id
            or self._ended_emitted
        ):
            return
        self._ended_emitted = True
        self._poll_timer.stop()
        self._set_status(PlaybackStatus.ENDED)
        self.ended.emit()

    def _stream_interrupted(self, request_id: str, message: str) -> None:
        if self._closed or request_id != self._request_id:
            return
        self._emit_error(message)

    def _apply_volume(self) -> None:
        if self._player is None:
            return
        try:
            self._player.volume = 0.0 if self._muted else self._volume * 100
        except Exception:
            LOGGER.exception("Could not apply libmpv volume")

    def _configure_stream_request(self, player: Any) -> None:
        headers = dict(self._stream_headers)
        user_agent = self._pop_header(headers, "user-agent")
        referrer = self._pop_header(headers, "referer")
        if user_agent:
            player.user_agent = user_agent
        if referrer:
            player.referrer = referrer
        player.http_header_fields = [
            f"{name}: {value}" for name, value in headers.items()
        ]
        version = getattr(player, "mpv_version_tuple", (0, 0, 0))
        if (
            self._stream_http_chunk_size is not None
            and isinstance(version, tuple)
            and version >= (0, 41, 0)
        ):
            try:
                player.curl_max_request_size = self._stream_http_chunk_size
            except Exception:
                LOGGER.warning(
                    "libmpv does not support curl-max-request-size; using its default",
                    exc_info=True,
                )

    def _apply_audio_output_device(self, player: Any) -> bool:
        if not self._audio_device_id:
            player.audio_device = "auto"
            return True
        devices = getattr(player, "audio_device_list", None)
        selected = self._match_audio_device(
            devices,
            self._audio_device_description,
            self._audio_device_native_id,
        )
        if selected is None:
            player.audio_device = "auto"
            LOGGER.warning(
                "Could not map Qt audio output to libmpv; using system default: %s",
                self._audio_device_description or self._audio_device_id,
            )
            return False
        player.audio_device = selected
        LOGGER.info(
            "Applied libmpv audio output: description=%s mpv_name=%s",
            self._audio_device_description,
            selected,
        )
        return True

    @staticmethod
    def _match_audio_device(
        devices: object,
        description: str,
        native_id: str,
    ) -> str | None:
        if not isinstance(devices, list):
            return None
        normalized_description = MpvAudioBackend._normalized_device_text(description)
        native_casefold = native_id.casefold()
        native_guids = {
            value.casefold()
            for value in re.findall(r"\{[0-9a-fA-F-]{32,38}\}", native_id)
        }
        best: tuple[int, str] | None = None
        for item in devices:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            candidate_description = item.get("description")
            if not isinstance(name, str) or not name or name == "auto":
                continue
            description_text = (
                candidate_description if isinstance(candidate_description, str) else ""
            )
            candidate_name = name.casefold()
            candidate_normalized = MpvAudioBackend._normalized_device_text(
                description_text
            )
            score = 0
            if native_casefold and native_casefold == candidate_name:
                score = 120
            elif native_casefold and native_casefold in candidate_name:
                score = 110
            elif native_guids and any(guid in candidate_name for guid in native_guids):
                score = 105
            elif (
                normalized_description
                and normalized_description == candidate_normalized
            ):
                score = 100
            elif (
                normalized_description
                and candidate_normalized
                and (
                    normalized_description in candidate_normalized
                    or candidate_normalized in normalized_description
                )
            ):
                score = 80
            if score and (best is None or score > best[0]):
                best = (score, name)
        return best[1] if best is not None else None

    @staticmethod
    def _normalized_device_text(value: str) -> str:
        return re.sub(r"[^0-9a-z가-힣]+", "", value.casefold())

    @staticmethod
    def _pop_header(headers: dict[str, str], target: str) -> str:
        key = next((name for name in headers if name.casefold() == target), None)
        return headers.pop(key) if key is not None else ""

    def _set_status(self, status: PlaybackStatus) -> None:
        if status is self._status:
            return
        if status is not PlaybackStatus.BUFFERING:
            self._buffer_timer.stop()
        self._status = status
        self.status_changed.emit(status)

    def _emit_error(self, message: str) -> None:
        self._prepare_timer.stop()
        self._buffer_timer.stop()
        self._poll_timer.stop()
        self._set_status(PlaybackStatus.ERROR)
        self.error_occurred.emit(message)
