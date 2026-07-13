from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from church_presenter.domain.enums import ChannelRole, PlaybackStatus
from church_presenter.domain.models import VideoPlaybackRuntimeState
from church_presenter.media.base import MediaPlaybackBackend

BackendFactory = Callable[[], MediaPlaybackBackend]
CUE_TIMEOUT_MS = 10_000
LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class _ChannelPlayers:
    preview_backend: MediaPlaybackBackend
    live_backend: MediaPlaybackBackend
    preview_state: VideoPlaybackRuntimeState = field(default_factory=VideoPlaybackRuntimeState)
    live_state: VideoPlaybackRuntimeState = field(default_factory=VideoPlaybackRuntimeState)
    preview_ready: bool = False
    preview_frame: QImage = field(default_factory=QImage)
    live_frame: QImage = field(default_factory=QImage)
    generation: int = 0


class VideoPlaybackManager(QObject):
    """Own independent prepared/live players for Broadcast and Venue."""

    preview_result = Signal(object, str, object, str)
    live_frame_ready = Signal(object, str, object)
    runtime_changed = Signal(object, object)
    play_started = Signal(object)
    live_ended = Signal(object)
    live_stopped = Signal(object)
    live_error = Signal(object, str)
    active_count_changed = Signal(int)

    def __init__(
        self, factory: BackendFactory, *, volume: float = 0.8, muted: bool = False
    ) -> None:
        super().__init__()
        self.volume = volume
        self.muted = muted
        self._closed = False
        self._active_roles: set[ChannelRole] = set()
        self._linked_transport_roles: frozenset[ChannelRole] = frozenset()
        self._channels = {
            role: _ChannelPlayers(factory(), factory())
            for role in (ChannelRole.BROADCAST, ChannelRole.VENUE)
        }
        for role, players in self._channels.items():
            for backend in (players.preview_backend, players.live_backend):
                self._connect_backend(role, backend)
            players.preview_backend.set_muted(True)
            players.live_backend.set_volume(volume)
            players.live_backend.set_muted(muted)

    def cue_preview(self, role: ChannelRole, path: Path) -> None:
        players = self._channels[role]
        resolved = path.expanduser().resolve()
        players.generation += 1
        generation = players.generation
        players.preview_ready = False
        players.preview_frame = QImage()
        players.preview_state = VideoPlaybackRuntimeState(
            path=resolved,
            status=PlaybackStatus.LOADING,
            volume=self.volume,
            is_muted=True,
        )
        players.preview_backend.set_muted(True)
        players.preview_backend.load(resolved)
        QTimer.singleShot(CUE_TIMEOUT_MS, lambda: self._cue_timeout(role, generation))

    def cue_both(self, path: Path) -> None:
        self.cue_preview(ChannelRole.BROADCAST, path)
        self.cue_preview(ChannelRole.VENUE, path)

    def activate_preview(self, role: ChannelRole, path: Path) -> bool:
        players = self._channels[role]
        resolved = path.expanduser().resolve()
        if (
            players.preview_ready
            and players.preview_state.status is PlaybackStatus.CUE
            and players.preview_backend.path == resolved
            and not players.preview_frame.isNull()
        ):
            old_live = players.live_backend
            if old_live.path is not None:
                old_live.stop()
            self._unlink_live_transport(role)
            players.live_backend, players.preview_backend = (
                players.preview_backend,
                old_live,
            )
            players.live_frame = QImage(players.preview_frame)
            players.live_state = VideoPlaybackRuntimeState(
                path=resolved,
                status=PlaybackStatus.LIVE_PAUSED,
                duration_ms=players.preview_state.duration_ms,
                volume=self.volume,
                is_muted=self.muted,
            )
            players.live_backend.set_volume(self.volume)
            players.live_backend.set_muted(self.muted)
            players.live_backend.seek(0)
            players.live_backend.pause()
            players.preview_ready = False
            players.preview_frame = QImage()
            players.preview_state = VideoPlaybackRuntimeState(
                volume=self.volume,
                is_muted=True,
            )
            self._set_active(role, False)
            self.live_frame_ready.emit(role, str(resolved), QImage(players.live_frame))
            self.runtime_changed.emit(role, players.live_state)
            return True
        return (
            players.live_backend.path == resolved
            and not players.live_frame.isNull()
            and players.live_state.status
            in {
                PlaybackStatus.LIVE_PAUSED,
                PlaybackStatus.PLAYING,
                PlaybackStatus.PAUSED,
            }
        )

    def can_activate(self, role: ChannelRole, path: Path) -> bool:
        """Return whether a prepared first frame can be committed without loading."""
        players = self._channels[role]
        resolved = path.expanduser().resolve()
        return (
            players.preview_ready
            and players.preview_state.status is PlaybackStatus.CUE
            and players.preview_backend.path == resolved
            and not players.preview_frame.isNull()
        ) or (
            players.live_backend.path == resolved
            and not players.live_frame.isNull()
            and players.live_state.status
            in {
                PlaybackStatus.LIVE_PAUSED,
                PlaybackStatus.PLAYING,
                PlaybackStatus.PAUSED,
            }
        )

    def play(self, role: ChannelRole) -> bool:
        roles = self._transport_roles(role)
        if not all(
            self._can_control(target, {PlaybackStatus.LIVE_PAUSED, PlaybackStatus.PAUSED})
            for target in roles
        ):
            return False
        for target in roles:
            players = self._channels[target]
            players.live_backend.play()
            players.live_state.status = PlaybackStatus.PLAYING
            self._set_active(target, True)
            self.runtime_changed.emit(target, players.live_state)
        self.play_started.emit(role)
        return True

    def pause(self, role: ChannelRole) -> None:
        roles = self._transport_roles(role)
        if not all(
            self._can_control(target, {PlaybackStatus.PLAYING}) for target in roles
        ):
            return
        for target in roles:
            players = self._channels[target]
            players.live_backend.pause()
            players.live_state.status = PlaybackStatus.PAUSED
            self._set_active(target, False)
            self.runtime_changed.emit(target, players.live_state)

    def stop(self, role: ChannelRole) -> bool:
        roles = self._transport_roles(role)
        controllable = {
            PlaybackStatus.LIVE_PAUSED,
            PlaybackStatus.PLAYING,
            PlaybackStatus.PAUSED,
        }
        if not all(self._can_control(target, controllable) for target in roles):
            return False
        for target in roles:
            players = self._channels[target]
            players.live_backend.stop()
            players.live_state.status = PlaybackStatus.STOPPED
            players.live_state.position_ms = 0
            self._set_active(target, False)
            self.runtime_changed.emit(target, players.live_state)
            self.live_stopped.emit(target)
        self._linked_transport_roles = frozenset()
        self._apply_live_audio_policy()
        return True

    def seek(self, role: ChannelRole, position_ms: int) -> None:
        roles = self._transport_roles(role)
        controllable = {
            PlaybackStatus.LIVE_PAUSED,
            PlaybackStatus.PLAYING,
            PlaybackStatus.PAUSED,
        }
        if not all(self._can_control(target, controllable) for target in roles):
            return
        for target in roles:
            self._channels[target].live_backend.seek(position_ms)

    def restart(self, role: ChannelRole) -> None:
        self.seek(role, 0)

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))
        for players in self._channels.values():
            players.live_state.volume = self.volume
            players.live_backend.set_volume(self.volume)

    def set_muted(self, muted: bool) -> None:
        self.muted = muted
        self._apply_live_audio_policy()

    def clear_live(self, role: ChannelRole) -> None:
        self._unlink_live_transport(role)
        players = self._channels[role]
        if players.live_backend.path is not None:
            players.live_backend.stop()
        players.live_state = VideoPlaybackRuntimeState(volume=self.volume, is_muted=self.muted)
        players.live_frame = QImage()
        self._set_active(role, False)
        self.runtime_changed.emit(role, players.live_state)

    def last_live_frame(self, role: ChannelRole) -> tuple[Path | None, QImage]:
        players = self._channels[role]
        return players.live_state.path, QImage(players.live_frame)

    def runtime(self, role: ChannelRole) -> VideoPlaybackRuntimeState:
        return self._channels[role].live_state

    def preview_runtime(self, role: ChannelRole) -> VideoPlaybackRuntimeState:
        """Expose prepared metadata without exposing a backend instance."""
        return self._channels[role].preview_state

    @property
    def active_count(self) -> int:
        return len(self._active_roles)

    @property
    def is_live_transport_linked(self) -> bool:
        """Return whether Broadcast and Venue share transport commands."""
        return len(self._linked_transport_roles) == 2

    def link_live_pair(self) -> bool:
        """Link transport when both channels contain the same cueable video."""
        roles = (ChannelRole.BROADCAST, ChannelRole.VENUE)
        first_path = self._channels[roles[0]].live_state.path
        linkable = {
            PlaybackStatus.LIVE_PAUSED,
            PlaybackStatus.PLAYING,
            PlaybackStatus.PAUSED,
        }
        if (
            first_path is None
            or self._channels[roles[1]].live_state.path != first_path
            or not all(self._can_control(role, linkable) for role in roles)
        ):
            self._linked_transport_roles = frozenset()
            self._apply_live_audio_policy()
            return False
        self._linked_transport_roles = frozenset(roles)
        self._apply_live_audio_policy()
        return True

    def close(self) -> None:
        self._closed = True
        self._linked_transport_roles = frozenset()
        for role, players in self._channels.items():
            players.generation += 1
            self._set_active(role, False)
            players.preview_backend.close()
            players.live_backend.close()

    def _connect_backend(self, role: ChannelRole, backend: MediaPlaybackBackend) -> None:
        backend.loaded.connect(lambda backend=backend: self._loaded(role, backend))
        backend.frame_ready.connect(
            lambda image, backend=backend: self._frame(role, backend, image)
        )
        backend.position_changed.connect(
            lambda position, backend=backend: self._position(role, backend, position)
        )
        backend.duration_changed.connect(
            lambda duration, backend=backend: self._duration(role, backend, duration)
        )
        backend.ended.connect(lambda backend=backend: self._ended(role, backend))
        backend.error_occurred.connect(
            lambda message, backend=backend: self._error(role, backend, message)
        )

    def _loaded(self, role: ChannelRole, backend: MediaPlaybackBackend) -> None:
        players = self._channels[role]
        if (
            backend is players.preview_backend
            and backend.path == players.preview_state.path
            and players.preview_state.status is PlaybackStatus.LOADING
        ):
            players.preview_state.status = PlaybackStatus.READY

    def _frame(self, role: ChannelRole, backend: MediaPlaybackBackend, image: QImage) -> None:
        players = self._channels[role]
        path = backend.path
        if path is None:
            return
        if backend is players.preview_backend:
            if (
                players.preview_state.path != path
                or players.preview_state.status
                not in {
                    PlaybackStatus.LOADING,
                    PlaybackStatus.READY,
                    PlaybackStatus.CUE,
                }
            ):
                return
            players.preview_frame = QImage(image)
            players.preview_ready = True
            players.preview_state.status = PlaybackStatus.CUE
            self.preview_result.emit(role, str(path), QImage(image), "")
        elif backend is players.live_backend:
            players.live_frame = QImage(image)
            self.live_frame_ready.emit(role, str(path), QImage(image))

    def _position(self, role: ChannelRole, backend: MediaPlaybackBackend, position: int) -> None:
        players = self._channels[role]
        if backend is players.live_backend:
            players.live_state.position_ms = position
            self.runtime_changed.emit(role, players.live_state)

    def _duration(self, role: ChannelRole, backend: MediaPlaybackBackend, duration: int) -> None:
        players = self._channels[role]
        if backend is players.preview_backend and backend.path == players.preview_state.path:
            players.preview_state.duration_ms = duration
        elif backend is players.live_backend:
            players.live_state.duration_ms = duration
            self.runtime_changed.emit(role, players.live_state)

    def _ended(self, role: ChannelRole, backend: MediaPlaybackBackend) -> None:
        players = self._channels[role]
        if backend is not players.live_backend:
            return
        self._unlink_live_transport(role)
        players.live_state.status = PlaybackStatus.ENDED
        self._set_active(role, False)
        self.runtime_changed.emit(role, players.live_state)
        self.live_ended.emit(role)

    def _error(self, role: ChannelRole, backend: MediaPlaybackBackend, message: str) -> None:
        players = self._channels[role]
        if backend is players.preview_backend:
            if backend.path != players.preview_state.path:
                return
            players.preview_ready = False
            players.preview_frame = QImage()
            players.preview_state.status = PlaybackStatus.ERROR
            players.preview_state.error_message = message
            path = str(players.preview_state.path or "")
            self.preview_result.emit(role, path, QImage(), message)
        elif backend is players.live_backend:
            self._unlink_live_transport(role)
            players.live_state.status = PlaybackStatus.ERROR
            players.live_state.error_message = message
            self._set_active(role, False)
            self.runtime_changed.emit(role, players.live_state)
            self.live_error.emit(role, message)

    def _cue_timeout(self, role: ChannelRole, generation: int) -> None:
        players = self._channels[role]
        if (
            self._closed
            or generation != players.generation
            or players.preview_ready
            or players.preview_state.status
            not in (
                PlaybackStatus.LOADING,
                PlaybackStatus.READY,
            )
        ):
            return
        path = str(players.preview_state.path or "")
        diagnostic = players.preview_backend.diagnostic()
        LOGGER.warning(
            "Video cue timed out: role=%s path=%s backend=(%s)",
            role.value,
            path,
            diagnostic,
        )
        players.preview_ready = False
        players.preview_frame = QImage()
        players.preview_backend.stop()
        players.preview_state.status = PlaybackStatus.ERROR
        players.preview_state.error_message = (
            "첫 영상 프레임을 10초 안에 준비하지 못했습니다. "
            "다시 Cue하거나 권장 MP4(H.264/AAC)로 변환해 보십시오."
        )
        self.preview_result.emit(role, path, QImage(), players.preview_state.error_message)

    def _set_active(self, role: ChannelRole, active: bool) -> None:
        before = len(self._active_roles)
        if active:
            self._active_roles.add(role)
        else:
            self._active_roles.discard(role)
        if len(self._active_roles) != before:
            self.active_count_changed.emit(len(self._active_roles))

    def _transport_roles(self, role: ChannelRole) -> tuple[ChannelRole, ...]:
        if role in self._linked_transport_roles:
            return (ChannelRole.BROADCAST, ChannelRole.VENUE)
        return (role,)

    def _unlink_live_transport(self, role: ChannelRole) -> None:
        if role in self._linked_transport_roles:
            self._linked_transport_roles = frozenset()
            self._apply_live_audio_policy()

    def _can_control(
        self, role: ChannelRole, statuses: set[PlaybackStatus]
    ) -> bool:
        players = self._channels[role]
        return (
            players.live_state.path is not None
            and players.live_backend.path == players.live_state.path
            and players.live_state.status in statuses
        )

    def _apply_live_audio_policy(self) -> None:
        for role, players in self._channels.items():
            linked_venue = (
                role is ChannelRole.VENUE and role in self._linked_transport_roles
            )
            effective_muted = self.muted or linked_venue
            players.live_state.is_muted = effective_muted
            players.live_backend.set_muted(effective_muted)
