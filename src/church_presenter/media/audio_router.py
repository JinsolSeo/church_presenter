from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from church_presenter.domain.enums import AudioSourceType, PlaybackStatus
from church_presenter.domain.models import PlaylistItem
from church_presenter.media.audio_backend import StreamingAudioBackend
from church_presenter.media.base import MediaPlaybackBackend


class AudioBackendRouter(QObject):
    """Route playlist items to Qt local audio or libmpv streaming audio."""

    loaded = Signal()
    position_changed = Signal(int)
    duration_changed = Signal(int)
    status_changed = Signal(object)
    ended = Signal()
    error_occurred = Signal(str)
    fallback_started = Signal(str)

    def __init__(
        self,
        local_backend: MediaPlaybackBackend,
        youtube_backend: StreamingAudioBackend,
    ) -> None:
        super().__init__()
        self.local_backend = local_backend
        self.youtube_backend = youtube_backend
        self._active: MediaPlaybackBackend | StreamingAudioBackend | None = None
        self._item: PlaylistItem | None = None
        self._using_fallback = False
        self._volume = 0.7
        self._muted = False
        self._connect(local_backend)
        self._connect(youtube_backend)

    def prepare(self, item: PlaylistItem) -> None:
        """Prepare the item's preferred source, stopping the previous backend."""
        self._item = item
        self._using_fallback = False
        if item.source_type is AudioSourceType.LOCAL_FILE:
            if item.path is None or not item.path.is_file():
                # A rejected source switch must also silence the previously
                # active track; otherwise status and audible output diverge.
                self.stop()
                self.error_occurred.emit("음악 파일을 찾을 수 없습니다.")
                return
            backend: MediaPlaybackBackend | StreamingAudioBackend = self.local_backend
            source: Path | str = item.path
        else:
            backend = self.youtube_backend
            source = item.source
        self._activate(backend)
        backend.set_volume(self._volume)
        backend.set_muted(self._muted)
        backend.load(source)  # type: ignore[arg-type]

    def play(self) -> None:
        if self._active is None:
            self.error_occurred.emit("재생할 배경음악이 준비되지 않았습니다.")
            return
        self._active.play()

    def pause(self) -> None:
        if self._active is not None:
            self._active.pause()

    def stop(self) -> None:
        active, self._active = self._active, None
        if active is not None:
            active.stop()
        self.position_changed.emit(0)
        self.status_changed.emit(PlaybackStatus.STOPPED)

    def seek(self, position_ms: int) -> None:
        if self._active is not None:
            self._active.seek(position_ms)

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))
        self.local_backend.set_volume(self._volume)
        self.youtube_backend.set_volume(self._volume)

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        self.local_backend.set_muted(muted)
        self.youtube_backend.set_muted(muted)

    def set_audio_output_device(self, device_id: str) -> bool:
        local_applied = self.local_backend.set_audio_output_device(device_id)
        self.youtube_backend.set_audio_output_device(device_id)
        return local_applied

    def close(self) -> None:
        self._active = None
        self._item = None
        self.local_backend.close()
        self.youtube_backend.close()

    def is_prepared(self, item: PlaylistItem) -> bool:
        """Return whether the requested item is already active and reusable."""
        return (
            self._item is not None
            and self._item.item_id == item.item_id
            and self._active is not None
            and self._active.status
            in {
                PlaybackStatus.READY,
                PlaybackStatus.CUE,
                PlaybackStatus.PLAYING,
                PlaybackStatus.PAUSED,
                PlaybackStatus.BUFFERING,
            }
        )

    @property
    def active_source_type(self) -> AudioSourceType | None:
        if self._active is self.local_backend:
            return AudioSourceType.LOCAL_FILE
        if self._active is self.youtube_backend:
            return AudioSourceType.YOUTUBE
        return None

    @property
    def using_fallback(self) -> bool:
        return self._using_fallback

    @property
    def status(self) -> PlaybackStatus:
        return self._active.status if self._active is not None else PlaybackStatus.UNLOADED

    @property
    def path(self) -> Path | None:
        return self.local_backend.path if self._active is self.local_backend else None

    def _activate(self, backend: MediaPlaybackBackend | StreamingAudioBackend) -> None:
        previous, self._active = self._active, None
        if previous is not None and previous is not backend:
            previous.stop()
        self._active = backend

    def _connect(self, backend: MediaPlaybackBackend | StreamingAudioBackend) -> None:
        backend.loaded.connect(lambda backend=backend: self._forward_loaded(backend))
        backend.position_changed.connect(
            lambda value, backend=backend: self._forward_position(backend, value)
        )
        backend.duration_changed.connect(
            lambda value, backend=backend: self._forward_duration(backend, value)
        )
        backend.status_changed.connect(
            lambda value, backend=backend: self._forward_status(backend, value)
        )
        backend.ended.connect(lambda backend=backend: self._forward_ended(backend))
        backend.error_occurred.connect(
            lambda message, backend=backend: self._backend_error(backend, message)
        )

    def _forward_loaded(self, backend: object) -> None:
        if backend is self._active:
            self.loaded.emit()

    def _forward_position(self, backend: object, value: int) -> None:
        if backend is self._active:
            self.position_changed.emit(value)

    def _forward_duration(self, backend: object, value: int) -> None:
        if backend is self._active:
            self.duration_changed.emit(value)

    def _forward_status(self, backend: object, value: PlaybackStatus) -> None:
        if backend is self._active:
            self.status_changed.emit(value)

    def _forward_ended(self, backend: object) -> None:
        if backend is self._active:
            self.ended.emit()

    def _backend_error(
        self,
        backend: MediaPlaybackBackend | StreamingAudioBackend,
        message: str,
    ) -> None:
        if backend is not self._active:
            return
        item = self._item
        fallback = item.fallback_path if item is not None else None
        if (
            backend is self.youtube_backend
            and not self._using_fallback
            and fallback is not None
            and fallback.is_file()
        ):
            self._using_fallback = True
            self._active = None
            backend.stop()
            self._active = self.local_backend
            notice = "Streaming failed — playing local fallback"
            self.fallback_started.emit(notice)
            self.local_backend.set_volume(self._volume)
            self.local_backend.set_muted(self._muted)
            self.local_backend.load(fallback)
            return
        if backend is self.youtube_backend and fallback is not None and not fallback.is_file():
            message = f"{message} 로컬 fallback 파일도 찾을 수 없습니다."
        elif backend is self.local_backend and self._using_fallback:
            message = f"로컬 fallback 재생 실패: {message}"
        self.error_occurred.emit(message)
