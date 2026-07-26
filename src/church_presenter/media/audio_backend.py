from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from church_presenter.domain.enums import PlaybackStatus


class StreamingAudioBackend(QObject):
    """Common transport contract for URL-based audio backends."""

    loaded = Signal()
    position_changed = Signal(int)
    duration_changed = Signal(int)
    status_changed = Signal(object)
    ended = Signal()
    error_occurred = Signal(str)

    def load(self, source: str) -> None:
        """Prepare a URL without starting playback."""
        raise NotImplementedError

    def play(self) -> None:
        raise NotImplementedError

    def pause(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def seek(self, position_ms: int) -> None:
        raise NotImplementedError

    def set_volume(self, volume: float) -> None:
        raise NotImplementedError

    def set_muted(self, muted: bool) -> None:
        raise NotImplementedError

    def set_audio_output_device(self, device_id: str) -> bool:
        """Apply an output device when the backend can map the application ID."""
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    @property
    def status(self) -> PlaybackStatus:
        raise NotImplementedError

    @property
    def source(self) -> str:
        raise NotImplementedError


class UnavailableStreamingBackend(StreamingAudioBackend):
    """Non-fatal placeholder used when YouTube runtime support is unavailable."""

    def __init__(self, message: str = "YouTube 재생 backend를 사용할 수 없습니다.") -> None:
        super().__init__()
        self.message = message
        self._source = ""
        self._status = PlaybackStatus.UNLOADED

    def load(self, source: str) -> None:
        self._source = source
        self._status = PlaybackStatus.ERROR
        self.status_changed.emit(self._status)
        self.error_occurred.emit(self.message)

    def play(self) -> None:
        self.error_occurred.emit(self.message)

    def pause(self) -> None:
        return

    def stop(self) -> None:
        self._status = PlaybackStatus.STOPPED
        self.status_changed.emit(self._status)

    def seek(self, position_ms: int) -> None:
        del position_ms

    def set_volume(self, volume: float) -> None:
        del volume

    def set_muted(self, muted: bool) -> None:
        del muted

    def set_audio_output_device(self, device_id: str) -> bool:
        return not device_id

    def close(self) -> None:
        self._source = ""
        self._status = PlaybackStatus.UNLOADED

    @property
    def status(self) -> PlaybackStatus:
        return self._status

    @property
    def source(self) -> str:
        return self._source
