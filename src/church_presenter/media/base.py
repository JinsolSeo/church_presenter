from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from church_presenter.domain.enums import PlaybackStatus


class MediaPlaybackBackend(QObject):
    """Replaceable local-media backend contract with Qt-neutral commands."""

    loaded = Signal()
    frame_ready = Signal(object)
    position_changed = Signal(int)
    duration_changed = Signal(int)
    status_changed = Signal(object)
    ended = Signal()
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def load(self, path: Path) -> None:
        """Cue a local media file without starting playback."""
        raise NotImplementedError

    def play(self) -> None:
        """Start playback after an explicit operator action."""
        raise NotImplementedError

    def pause(self) -> None:
        """Pause playback."""
        raise NotImplementedError

    def stop(self) -> None:
        """Stop playback and seek to the beginning."""
        raise NotImplementedError

    def seek(self, position_ms: int) -> None:
        """Seek to a millisecond position."""
        raise NotImplementedError

    def set_volume(self, volume: float) -> None:
        """Set linear volume in the inclusive 0..1 range."""
        raise NotImplementedError

    def set_muted(self, muted: bool) -> None:
        """Mute or unmute audio output."""
        raise NotImplementedError

    def close(self) -> None:
        """Release backend resources."""
        raise NotImplementedError

    def diagnostic(self) -> str:
        """Return non-sensitive backend state for timeout diagnostics."""
        return f"status={self.status.value}, path={self.path}"

    @property
    def status(self) -> PlaybackStatus:
        """Return current backend state."""
        raise NotImplementedError

    @property
    def path(self) -> Path | None:
        """Return the loaded local path."""
        raise NotImplementedError
