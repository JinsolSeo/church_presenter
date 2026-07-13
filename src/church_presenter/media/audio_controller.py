from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from church_presenter.domain.enums import PauseReason, PlaybackStatus, RepeatMode
from church_presenter.domain.models import (
    AudioPlaybackRuntimeState,
    AudioPlaylist,
    PlaylistItem,
)
from church_presenter.media.base import MediaPlaybackBackend


class AudioPlaybackController(QObject):
    """Application-wide background-music playlist and playback policy."""

    runtime_changed = Signal(object)
    playlist_changed = Signal(object)
    track_changed = Signal(int)
    error_occurred = Signal(str)

    def __init__(
        self,
        backend: MediaPlaybackBackend,
        playlist: AudioPlaylist | None = None,
        *,
        volume: float = 0.7,
        muted: bool = False,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.playlist = playlist or AudioPlaylist()
        self.runtime = AudioPlaybackRuntimeState(volume=volume, is_muted=muted)
        self._pending_play = False
        self._pending_seek_ms: int | None = None
        backend.loaded.connect(self._loaded)
        backend.position_changed.connect(self._position_changed)
        backend.duration_changed.connect(self._duration_changed)
        backend.status_changed.connect(self._status_changed)
        backend.ended.connect(self._ended)
        backend.error_occurred.connect(self._error)
        backend.set_volume(volume)
        backend.set_muted(muted)

    def add_paths(self, paths: list[Path]) -> None:
        existing = {item.path.resolve() for item in self.playlist.items}
        for path in paths:
            resolved = path.expanduser().resolve()
            if resolved in existing:
                continue
            available = resolved.is_file()
            self.playlist.add(
                PlaylistItem(
                    item_id=str(resolved),
                    path=resolved,
                    title=resolved.stem,
                    is_available=available,
                    error_message="" if available else "파일을 찾을 수 없습니다.",
                )
            )
            existing.add(resolved)
        self.playlist_changed.emit(self.playlist)

    def remove(self, index: int) -> None:
        current = self.playlist.current_index
        self.playlist.remove(index)
        if current == index:
            self.stop()
        self.playlist_changed.emit(self.playlist)

    def clear(self) -> None:
        self.stop()
        self.playlist.clear()
        self.playlist_changed.emit(self.playlist)

    def move(self, source: int, destination: int) -> None:
        self.playlist.move(source, destination)
        self.playlist_changed.emit(self.playlist)

    def play(self, index: int | None = None) -> bool:
        if index is not None:
            if not 0 <= index < len(self.playlist.items):
                return False
            self.playlist.current_index = index
        item = self.playlist.current_item
        if item is None:
            return False
        if not item.path.is_file():
            self._error("음악 파일을 찾을 수 없습니다.")
            return False
        self.runtime.pause_reason = PauseReason.NONE
        if self.backend.path != item.path.resolve():
            self._pending_play = True
            self.runtime.path = item.path
            self.runtime.status = PlaybackStatus.LOADING
            self.runtime.position_ms = 0
            self.backend.load(item.path)
        else:
            self.backend.play()
        self.track_changed.emit(self.playlist.current_index or 0)
        self.runtime_changed.emit(self.runtime)
        return True

    def cue_current(self, position_ms: int = 0) -> bool:
        """Restore the selected track without starting playback."""
        item = self.playlist.current_item
        if item is None or not item.path.is_file():
            return False
        self._pending_play = False
        self._pending_seek_ms = max(0, position_ms)
        self.runtime.path = item.path
        self.runtime.status = PlaybackStatus.LOADING
        self.runtime.position_ms = self._pending_seek_ms
        self.backend.load(item.path)
        if self.playlist.current_index is not None:
            self.track_changed.emit(self.playlist.current_index)
        self.runtime_changed.emit(self.runtime)
        return True

    def pause(self, reason: PauseReason = PauseReason.USER) -> None:
        if self.runtime.status is not PlaybackStatus.PLAYING:
            return
        self.backend.pause()
        self.runtime.status = PlaybackStatus.PAUSED
        self.runtime.pause_reason = reason
        self.runtime_changed.emit(self.runtime)

    def pause_for_video(self) -> bool:
        if self.runtime.status is not PlaybackStatus.PLAYING:
            return False
        self.pause(PauseReason.VIDEO)
        return True

    def stop(self) -> None:
        self._pending_play = False
        self.backend.stop()
        self.runtime.status = PlaybackStatus.STOPPED
        self.runtime.position_ms = 0
        self.runtime.pause_reason = PauseReason.NONE
        self.runtime_changed.emit(self.runtime)

    def next(self) -> bool:
        index = self.playlist.next_index()
        return False if index is None else self.play(index)

    def previous(self) -> bool:
        index = self.playlist.previous_index(self.runtime.position_ms)
        if index is None:
            return False
        if index == self.playlist.current_index:
            self.backend.seek(0)
            return True
        return self.play(index)

    def seek(self, position_ms: int) -> None:
        self.backend.seek(position_ms)

    def set_volume(self, volume: float) -> None:
        self.runtime.volume = max(0.0, min(1.0, volume))
        self.backend.set_volume(self.runtime.volume)
        self.runtime_changed.emit(self.runtime)

    def set_muted(self, muted: bool) -> None:
        self.runtime.is_muted = muted
        self.backend.set_muted(muted)
        self.runtime_changed.emit(self.runtime)

    def set_repeat_mode(self, mode: RepeatMode) -> None:
        self.playlist.repeat_mode = mode
        self.playlist.is_modified = True
        self.playlist_changed.emit(self.playlist)

    def replace_playlist(self, playlist: AudioPlaylist) -> None:
        self.stop()
        self.playlist = playlist
        self.playlist_changed.emit(self.playlist)

    def close(self) -> None:
        self.stop()
        self.backend.close()

    def _loaded(self) -> None:
        self.runtime.status = PlaybackStatus.CUE
        if self._pending_seek_ms is not None:
            position = self._pending_seek_ms
            self._pending_seek_ms = None
            self.backend.seek(position)
        if self._pending_play:
            self._pending_play = False
            self.backend.play()

    def _position_changed(self, position: int) -> None:
        self.runtime.position_ms = position
        self.runtime_changed.emit(self.runtime)

    def _duration_changed(self, duration: int) -> None:
        self.runtime.duration_ms = duration
        item = self.playlist.current_item
        if item is not None and item.duration_ms != duration:
            assert self.playlist.current_index is not None
            self.playlist.items[self.playlist.current_index] = replace(
                item,
                duration_ms=duration,
            )
            self.playlist_changed.emit(self.playlist)
        self.runtime_changed.emit(self.runtime)

    def _status_changed(self, status: PlaybackStatus) -> None:
        self.runtime.status = status
        self.runtime_changed.emit(self.runtime)

    def _ended(self) -> None:
        index = self.playlist.next_index(ended=True)
        if index is None:
            self.runtime.status = PlaybackStatus.STOPPED
            self.runtime.position_ms = 0
            self.runtime_changed.emit(self.runtime)
            return
        if index == self.playlist.current_index and self.playlist.repeat_mode is RepeatMode.ONE:
            self.backend.seek(0)
            self.backend.play()
            return
        self.play(index)

    def _error(self, message: str) -> None:
        self._pending_play = False
        self.runtime.status = PlaybackStatus.ERROR
        self.runtime.error_message = message
        self.runtime_changed.emit(self.runtime)
        self.error_occurred.emit(message)
