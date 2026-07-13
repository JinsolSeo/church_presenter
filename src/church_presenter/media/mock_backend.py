from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QImage

from church_presenter.domain.enums import PlaybackStatus
from church_presenter.media.base import MediaPlaybackBackend


class MockMediaBackend(MediaPlaybackBackend):
    """Deterministic codec-free backend for unit and offscreen GUI tests."""

    def __init__(
        self,
        *,
        video: bool = False,
        duration_ms: int = 10_000,
        auto_frame: bool = True,
    ) -> None:
        super().__init__()
        self.video = video
        self.auto_frame = auto_frame
        self.duration_ms = duration_ms
        self.position_ms = 0
        self.volume = 1.0
        self.muted = False
        self._path: Path | None = None
        self._status = PlaybackStatus.UNLOADED
        self.fail_paths: set[Path] = set()
        self.closed = False

    def load(self, path: Path) -> None:
        resolved = path.resolve()
        self._path = resolved
        if resolved in self.fail_paths or not resolved.is_file():
            self._set_status(PlaybackStatus.ERROR)
            self.error_occurred.emit("Mock backend could not load media.")
            return
        self.position_ms = 0
        self._set_status(PlaybackStatus.READY)
        self.duration_changed.emit(self.duration_ms)
        self.loaded.emit()
        if self.video and self.auto_frame:
            self.emit_video_frame()

    def play(self) -> None:
        if self._path is None:
            self.error_occurred.emit("No mock media loaded.")
            return
        self._set_status(PlaybackStatus.PLAYING)

    def pause(self) -> None:
        self._set_status(PlaybackStatus.PAUSED)

    def stop(self) -> None:
        self.position_ms = 0
        self.position_changed.emit(0)
        self._set_status(PlaybackStatus.STOPPED)

    def seek(self, position_ms: int) -> None:
        self.position_ms = max(0, min(self.duration_ms, position_ms))
        self.position_changed.emit(self.position_ms)

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))

    def set_muted(self, muted: bool) -> None:
        self.muted = muted

    def close(self) -> None:
        self.stop()
        self.closed = True
        self._path = None
        self._set_status(PlaybackStatus.UNLOADED)

    @property
    def status(self) -> PlaybackStatus:
        return self._status

    @property
    def path(self) -> Path | None:
        return self._path

    def finish(self) -> None:
        self.position_ms = self.duration_ms
        self.position_changed.emit(self.position_ms)
        self._set_status(PlaybackStatus.ENDED)
        self.ended.emit()

    def fail(self, message: str = "Mock playback error") -> None:
        self._set_status(PlaybackStatus.ERROR)
        self.error_occurred.emit(message)

    def emit_video_frame(self, color: str = "#1d4ed8") -> None:
        """Deliver a decoded frame on demand for readiness tests."""
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        self.frame_ready.emit(image)

    def _set_status(self, status: PlaybackStatus) -> None:
        self._status = status
        self.status_changed.emit(status)
