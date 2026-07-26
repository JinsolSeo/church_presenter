from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

from church_presenter.domain.enums import (
    AudioAvailability,
    AudioSourceType,
    PauseReason,
    PlaybackStatus,
    RepeatMode,
)
from church_presenter.domain.models import (
    AudioPlaybackRuntimeState,
    AudioPlaylist,
    PlaylistItem,
)
from church_presenter.media.audio_backend import StreamingAudioBackend
from church_presenter.media.audio_router import AudioBackendRouter
from church_presenter.media.base import MediaPlaybackBackend
from church_presenter.media.mpv_audio_backend import MpvAudioBackend
from church_presenter.media.youtube_resolver import (
    YouTubeMetadata,
    YouTubeWorkerService,
    validate_youtube_url,
)


class AudioPlaybackController(QObject):
    """Application-wide mixed-source playlist and playback policy."""

    runtime_changed = Signal(object)
    playlist_changed = Signal(object)
    track_changed = Signal(int)
    error_occurred = Signal(str)

    def __init__(
        self,
        backend: MediaPlaybackBackend,
        playlist: AudioPlaylist | None = None,
        *,
        router: AudioBackendRouter | None = None,
        streaming_backend: StreamingAudioBackend | None = None,
        metadata_service: YouTubeWorkerService | None = None,
        volume: float = 0.7,
        muted: bool = False,
    ) -> None:
        super().__init__()
        # ``backend`` remains public for compatibility and audio-device diagnostics;
        # all transport commands go through the router.
        self.backend = backend
        self.router = router or AudioBackendRouter(
            backend,
            streaming_backend or MpvAudioBackend(),
        )
        self.metadata_service = metadata_service or YouTubeWorkerService()
        self.playlist = playlist or AudioPlaylist()
        self.runtime = AudioPlaybackRuntimeState(volume=volume, is_muted=muted)
        self._pending_play = False
        self._pending_seek_ms: int | None = None
        self._closed = False
        self.router.loaded.connect(self._loaded)
        self.router.position_changed.connect(self._position_changed)
        self.router.duration_changed.connect(self._duration_changed)
        self.router.status_changed.connect(self._status_changed)
        self.router.ended.connect(self._ended)
        self.router.error_occurred.connect(self._error)
        self.router.fallback_started.connect(self._fallback_started)
        self.metadata_service.resolved.connect(self._metadata_resolved)
        self.metadata_service.failed.connect(self._metadata_failed)
        self.router.set_volume(volume)
        self.router.set_muted(muted)
        self._refresh_unresolved_metadata()

    def add_paths(self, paths: list[Path]) -> None:
        existing = {
            item.path.resolve()
            for item in self.playlist.items
            if item.source_type is AudioSourceType.LOCAL_FILE and item.path is not None
        }
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

    def add_youtube_url(self, url: str) -> str:
        """Add a URL immediately and resolve its metadata asynchronously."""
        cleaned = validate_youtube_url(url)
        existing = next(
            (
                item
                for item in self.playlist.items
                if item.source_type is AudioSourceType.YOUTUBE and item.source == cleaned
            ),
            None,
        )
        if existing is not None:
            return existing.item_id
        item_id = uuid4().hex
        item = PlaylistItem.youtube(item_id, cleaned, title="YouTube 정보 불러오는 중…")
        self.playlist.add(item)
        self.playlist_changed.emit(self.playlist)
        self.metadata_service.request_metadata(item_id, cleaned)
        return item_id

    def retry_youtube(self, index: int) -> bool:
        if not 0 <= index < len(self.playlist.items):
            return False
        item = self.playlist.items[index]
        if item.source_type is not AudioSourceType.YOUTUBE:
            return False
        self.playlist.items[index] = replace(
            item,
            availability=AudioAvailability.UNRESOLVED,
            is_available=False,
            error_message="",
        )
        self.playlist.is_modified = True
        self.playlist_changed.emit(self.playlist)
        return self.metadata_service.request_metadata(item.item_id, item.source)

    def set_fallback(self, index: int, path: Path | None) -> bool:
        if not 0 <= index < len(self.playlist.items):
            return False
        item = self.playlist.items[index]
        if item.source_type is not AudioSourceType.YOUTUBE:
            return False
        fallback = path.expanduser().resolve() if path is not None else None
        self.playlist.items[index] = replace(item, fallback_path=fallback)
        self.playlist.is_modified = True
        self.playlist_changed.emit(self.playlist)
        return True

    def remove(self, index: int) -> None:
        if not 0 <= index < len(self.playlist.items):
            return
        current = self.playlist.current_index
        removed = self.playlist.remove(index)
        self.metadata_service.cancel(removed.item_id)
        if current == index:
            self.stop()
            self._clear_runtime_item()
            self.runtime.status = PlaybackStatus.STOPPED
            self.runtime_changed.emit(self.runtime)
        self.playlist_changed.emit(self.playlist)

    def clear(self) -> None:
        for item in self.playlist.items:
            self.metadata_service.cancel(item.item_id)
        self.stop()
        self.playlist.clear()
        self._clear_runtime_item()
        self.playlist_changed.emit(self.playlist)
        self.runtime_changed.emit(self.runtime)

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
        self._pending_play = False
        self._pending_seek_ms = None
        self._set_runtime_item(item)
        if item.source_type is AudioSourceType.LOCAL_FILE and (
            item.path is None or not item.path.is_file()
        ):
            # Never leave the previous track audibly playing while the UI reports
            # that the newly selected (missing) track failed.
            self.router.stop()
            self.runtime.position_ms = 0
            self._error("음악 파일을 찾을 수 없습니다.")
            return False
        self.runtime.pause_reason = PauseReason.NONE
        self.runtime.error_message = ""
        self.runtime.status_message = ""
        self.runtime.using_fallback = False
        if self.router.is_prepared(item):
            self.router.play()
        else:
            self._pending_play = True
            self.runtime.status = (
                PlaybackStatus.PREPARING
                if item.source_type is AudioSourceType.YOUTUBE
                else PlaybackStatus.LOADING
            )
            self.runtime.position_ms = 0
            self.router.prepare(item)
        if self.playlist.current_index is not None:
            self.track_changed.emit(self.playlist.current_index)
        self.runtime_changed.emit(self.runtime)
        return True

    def cue_current(self, position_ms: int = 0) -> bool:
        """Restore the selected item without starting playback."""
        item = self.playlist.current_item
        if item is None:
            return False
        if item.source_type is AudioSourceType.LOCAL_FILE and (
            item.path is None or not item.path.is_file()
        ):
            return False
        self._pending_play = False
        self._pending_seek_ms = max(0, position_ms)
        self._set_runtime_item(item)
        self.runtime.status = (
            PlaybackStatus.PREPARING
            if item.source_type is AudioSourceType.YOUTUBE
            else PlaybackStatus.LOADING
        )
        self.runtime.position_ms = self._pending_seek_ms
        self.router.prepare(item)
        if self.playlist.current_index is not None:
            self.track_changed.emit(self.playlist.current_index)
        self.runtime_changed.emit(self.runtime)
        return True

    def pause(self, reason: PauseReason = PauseReason.USER) -> None:
        if self.runtime.status not in {PlaybackStatus.PLAYING, PlaybackStatus.BUFFERING}:
            return
        self.router.pause()
        self.runtime.status = PlaybackStatus.PAUSED
        self.runtime.pause_reason = reason
        self.runtime_changed.emit(self.runtime)

    def pause_for_video(self) -> bool:
        if self.runtime.status not in {PlaybackStatus.PLAYING, PlaybackStatus.BUFFERING}:
            return False
        self.pause(PauseReason.VIDEO)
        return True

    def stop(self) -> None:
        self._pending_play = False
        self._pending_seek_ms = None
        self.router.stop()
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
            self.router.seek(0)
            return True
        return self.play(index)

    def seek(self, position_ms: int) -> None:
        self.router.seek(position_ms)

    def set_volume(self, volume: float) -> None:
        self.runtime.volume = max(0.0, min(1.0, volume))
        self.router.set_volume(self.runtime.volume)
        self.runtime_changed.emit(self.runtime)

    def set_muted(self, muted: bool) -> None:
        self.runtime.is_muted = muted
        self.router.set_muted(muted)
        self.runtime_changed.emit(self.runtime)

    def set_audio_output_device(self, device_id: str) -> bool:
        return self.router.set_audio_output_device(device_id)

    def set_repeat_mode(self, mode: RepeatMode) -> None:
        self.playlist.repeat_mode = mode
        self.playlist.is_modified = True
        self.playlist_changed.emit(self.playlist)

    def replace_playlist(self, playlist: AudioPlaylist) -> None:
        self.stop()
        for item in self.playlist.items:
            self.metadata_service.cancel(item.item_id)
        self.playlist = playlist
        self._clear_runtime_item()
        self._refresh_unresolved_metadata()
        self.playlist_changed.emit(self.playlist)
        self.runtime_changed.emit(self.runtime)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pending_play = False
        self.metadata_service.close()
        self.router.close()

    def _loaded(self) -> None:
        self.runtime.status = PlaybackStatus.CUE
        if self._pending_seek_ms is not None:
            position = self._pending_seek_ms
            self._pending_seek_ms = None
            self.router.seek(position)
        if self._pending_play:
            self._pending_play = False
            self.router.play()
        self.runtime_changed.emit(self.runtime)

    def _position_changed(self, position: int) -> None:
        self.runtime.position_ms = position
        self.runtime_changed.emit(self.runtime)

    def _duration_changed(self, duration: int) -> None:
        self.runtime.duration_ms = duration
        item = self.playlist.current_item
        if (
            item is not None
            and item.duration_ms != duration
            and not self.runtime.using_fallback
        ):
            assert self.playlist.current_index is not None
            self.playlist.items[self.playlist.current_index] = replace(item, duration_ms=duration)
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
            self.router.seek(0)
            self.router.play()
            return
        self.play(index)

    def _error(self, message: str) -> None:
        self._pending_play = False
        self.runtime.status = PlaybackStatus.ERROR
        self.runtime.error_message = message
        self.runtime.status_message = message
        self.runtime_changed.emit(self.runtime)
        self.error_occurred.emit(message)

    def _fallback_started(self, message: str) -> None:
        item = self.playlist.current_item
        self.runtime.using_fallback = True
        self.runtime.source_type = AudioSourceType.LOCAL_FILE
        self.runtime.path = item.fallback_path if item is not None else None
        self.runtime.status = PlaybackStatus.LOADING
        self.runtime.status_message = message
        self.runtime.error_message = ""
        self.runtime_changed.emit(self.runtime)

    def _metadata_resolved(self, item_id: str, result: object) -> None:
        if self._closed or not isinstance(result, YouTubeMetadata):
            return
        index = self._find_item(item_id)
        if index is None:
            return
        item = self.playlist.items[index]
        if item.source_type is not AudioSourceType.YOUTUBE:
            return
        self.playlist.items[index] = replace(
            item,
            title=result.title,
            duration_ms=result.duration_ms,
            is_available=True,
            availability=AudioAvailability.READY,
            error_message="",
            metadata=result.as_playlist_metadata(),
        )
        self.playlist.is_modified = True
        self.playlist_changed.emit(self.playlist)

    def _metadata_failed(self, item_id: str, message: str) -> None:
        if self._closed:
            return
        index = self._find_item(item_id)
        if index is None:
            return
        item = self.playlist.items[index]
        if item.source_type is not AudioSourceType.YOUTUBE:
            return
        self.playlist.items[index] = replace(
            item,
            is_available=False,
            availability=AudioAvailability.UNAVAILABLE,
            error_message=message,
        )
        self.playlist.is_modified = True
        self.playlist_changed.emit(self.playlist)

    def _refresh_unresolved_metadata(self) -> None:
        for item in self.playlist.items:
            if (
                item.source_type is AudioSourceType.YOUTUBE
                and item.availability is AudioAvailability.UNRESOLVED
            ):
                self.metadata_service.request_metadata(item.item_id, item.source)

    def _find_item(self, item_id: str) -> int | None:
        return next(
            (
                index
                for index, item in enumerate(self.playlist.items)
                if item.item_id == item_id
            ),
            None,
        )

    def _set_runtime_item(self, item: PlaylistItem) -> None:
        self.runtime.path = item.path
        self.runtime.source_type = item.source_type
        self.runtime.source = item.source
        self.runtime.title = item.title
        self.runtime.duration_ms = item.duration_ms or 0

    def _clear_runtime_item(self) -> None:
        """Clear stale track metadata after a playlist source is replaced."""
        self.runtime.path = None
        self.runtime.source_type = None
        self.runtime.source = ""
        self.runtime.title = ""
        self.runtime.position_ms = 0
        self.runtime.duration_ms = 0
        self.runtime.pause_reason = PauseReason.NONE
        self.runtime.error_message = ""
        self.runtime.status_message = ""
        self.runtime.using_fallback = False
