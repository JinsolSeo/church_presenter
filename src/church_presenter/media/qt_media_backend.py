from __future__ import annotations

import os
from collections.abc import Callable
from uuid import uuid4

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtMultimedia import (
    QAudioDevice,
    QAudioOutput,
    QMediaPlayer,
    QVideoFrame,
    QVideoSink,
)

from church_presenter.domain.enums import PlaybackStatus
from church_presenter.media.base import MediaPlaybackBackend, MediaSource
from church_presenter.media.youtube_resolver import (
    ResolvedYouTubeStream,
    YouTubeWorkerService,
    validate_youtube_url,
)


class QtMediaBackend(MediaPlaybackBackend):
    """Qt Multimedia adapter used for local video and background audio."""

    def __init__(
        self,
        *,
        video: bool = False,
        audio_device_resolver: Callable[[str], QAudioDevice | None] | None = None,
    ) -> None:
        super().__init__()
        self._audio_device_resolver = audio_device_resolver
        self._path: MediaSource | None = None
        self._status = PlaybackStatus.UNLOADED
        self._load_generation = 0
        self._load_pending = False
        self._source_started = False
        self._priming_video = False
        self._accept_video_frames = False
        self._youtube_request_id = ""
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.video_sink = QVideoSink(self) if video else None
        if self.video_sink is not None:
            self.player.setVideoOutput(self.video_sink)
            self.video_sink.videoFrameChanged.connect(self._video_frame_changed)
        self.youtube_worker = YouTubeWorkerService() if video else None
        if self.youtube_worker is not None:
            self.youtube_worker.resolved.connect(self._youtube_resolved)
            self.youtube_worker.failed.connect(self._youtube_failed)
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.player.positionChanged.connect(
            lambda position: self.position_changed.emit(int(position))
        )
        self.player.durationChanged.connect(
            lambda duration: self.duration_changed.emit(int(duration))
        )
        self.player.errorOccurred.connect(self._error_occurred)

    def load(self, path: MediaSource) -> None:
        # Invalidate and silence the old source before validating the new one.
        # Failed source changes must not leave earlier media playing behind an
        # ERROR state.
        self._load_generation += 1
        generation = self._load_generation
        self._load_pending = False
        self._source_started = False
        self._priming_video = False
        self._accept_video_frames = False
        self.player.stop()
        self.player.setSource(QUrl())
        if self._youtube_request_id and self.youtube_worker is not None:
            self.youtube_worker.cancel(self._youtube_request_id)
        self._youtube_request_id = ""
        if isinstance(path, str):
            try:
                source = validate_youtube_url(path)
            except ValueError as error:
                self._path = path
                self._emit_error(str(error))
                return
            self._path = source
            self._load_pending = True
            self._set_status(PlaybackStatus.LOADING)
            if self.youtube_worker is None:
                self._emit_error("YouTube 영상 backend이 준비되지 않았습니다.")
                return
            self._youtube_request_id = uuid4().hex
            if not self.youtube_worker.request_video_stream(
                self._youtube_request_id,
                source,
            ):
                self._emit_error("YouTube 영상 준비 요청을 시작하지 못했습니다.")
            return
        resolved = path.expanduser().resolve()
        self._path = resolved
        if not resolved.is_file():
            self._emit_error("미디어 파일을 찾을 수 없습니다.")
            return
        if not os.access(resolved, os.R_OK):
            self._emit_error("미디어 파일을 읽을 권한이 없습니다.")
            return
        self._load_pending = True
        # QMediaPlayer may treat setSource() with the current URL as a no-op.
        # Clearing first also flushes decoded frames from the previous cue.
        self._set_status(PlaybackStatus.LOADING)
        media_url = QUrl.fromLocalFile(str(resolved))
        QTimer.singleShot(
            0,
            lambda: self._start_source(generation, resolved, media_url),
        )

    def play(self) -> None:
        if self._path is None:
            self._emit_error("재생할 미디어가 로드되지 않았습니다.")
            return
        self.player.play()

    def pause(self) -> None:
        self.player.pause()

    def stop(self) -> None:
        self._load_generation += 1
        self._load_pending = False
        self._source_started = False
        self._priming_video = False
        self._accept_video_frames = False
        if self._youtube_request_id and self.youtube_worker is not None:
            self.youtube_worker.cancel(self._youtube_request_id)
        self._youtube_request_id = ""
        self.player.stop()
        self.player.setPosition(0)
        self._set_status(PlaybackStatus.STOPPED)

    def seek(self, position_ms: int) -> None:
        self.player.setPosition(max(0, position_ms))

    def set_volume(self, volume: float) -> None:
        self.audio_output.setVolume(max(0.0, min(1.0, volume)))

    def set_muted(self, muted: bool) -> None:
        self.audio_output.setMuted(muted)

    def set_audio_output_device(self, device_id: str) -> bool:
        if not device_id:
            self.audio_output.setDevice(QAudioDevice())
            return True
        if self._audio_device_resolver is None:
            return False
        device = self._audio_device_resolver(device_id)
        if device is None or device.isNull():
            return False
        self.audio_output.setDevice(device)
        return True

    def close(self) -> None:
        self._load_generation += 1
        self._load_pending = False
        self._source_started = False
        self._priming_video = False
        self._accept_video_frames = False
        if self._youtube_request_id and self.youtube_worker is not None:
            self.youtube_worker.cancel(self._youtube_request_id)
        self._youtube_request_id = ""
        self.player.stop()
        self.player.setSource(QUrl())
        if self.youtube_worker is not None:
            self.youtube_worker.close()
        self._path = None
        self._set_status(PlaybackStatus.UNLOADED)

    def diagnostic(self) -> str:
        media_status = self.player.mediaStatus().name
        playback_state = self.player.playbackState().name
        error = self.player.errorString().strip() or "none"
        return (
            f"status={self._status.value}, media_status={media_status}, "
            f"playback_state={playback_state}, load_pending={self._load_pending}, "
            f"youtube_pending={bool(self._youtube_request_id)}, "
            f"priming={self._priming_video}, position_ms={self.player.position()}, "
            f"duration_ms={self.player.duration()}, error={error}"
        )

    @property
    def status(self) -> PlaybackStatus:
        return self._status

    @property
    def path(self) -> MediaSource | None:
        return self._path

    def _set_status(self, status: PlaybackStatus) -> None:
        if status is self._status:
            return
        self._status = status
        self.status_changed.emit(status)

    def _start_source(
        self,
        generation: int,
        source: MediaSource,
        media_url: QUrl,
    ) -> None:
        if generation != self._load_generation or self._path != source:
            return
        self._source_started = True
        self.player.setSource(media_url)

    def _youtube_resolved(self, request_id: str, result: object) -> None:
        if request_id != self._youtube_request_id or not isinstance(
            result, ResolvedYouTubeStream
        ):
            return
        self._youtube_request_id = ""
        source = self._path
        if not isinstance(source, str):
            return
        self._start_source(self._load_generation, source, QUrl(result.stream_url))

    def _youtube_failed(self, request_id: str, message: str) -> None:
        if request_id != self._youtube_request_id:
            return
        self._youtube_request_id = ""
        self._emit_error(message)

    def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            if not self._load_pending or not self._source_started:
                return
            self._load_pending = False
            self.player.setPosition(0)
            self._set_status(PlaybackStatus.READY)
            if self.video_sink is not None:
                self.loaded.emit()
                # Preview backends are muted by their manager. Decode only until
                # the first real frame is available, then pause at the beginning.
                generation = self._load_generation
                self._priming_video = True
                self._accept_video_frames = True
                self.player.play()
                QTimer.singleShot(1500, lambda: self._retry_priming(generation, 100))
                QTimer.singleShot(4000, lambda: self._retry_priming(generation, 500))
            else:
                # Establish the prepared/paused state before notifying the
                # controller. The loaded signal can synchronously request Play;
                # pausing after that request makes the first click platform
                # dependent and leaves Windows backends paused.
                self.player.pause()
                self.loaded.emit()
        elif status is QMediaPlayer.MediaStatus.EndOfMedia:
            self._set_status(PlaybackStatus.ENDED)
            self.ended.emit()
        elif status is QMediaPlayer.MediaStatus.InvalidMedia:
            if self._source_started:
                self._emit_error(
                    self.player.errorString() or "지원하지 않거나 손상된 미디어입니다."
                )

    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if self._load_pending or self._priming_video:
            return
        if state is QMediaPlayer.PlaybackState.PlayingState:
            self._set_status(PlaybackStatus.PLAYING)
        elif state is QMediaPlayer.PlaybackState.PausedState:
            self._set_status(PlaybackStatus.PAUSED)

    def _video_frame_changed(self, frame: QVideoFrame) -> None:
        if not self._accept_video_frames or not frame.isValid():
            return
        if self._priming_video:
            image = frame.toImage()
            if not image.isNull():
                self.player.pause()
                self.player.setPosition(0)
                self._priming_video = False
                self._set_status(PlaybackStatus.READY)
                self.frame_ready.emit(image)
            return
        # Preserve the native video frame during Live playback. Converting every
        # frame to QImage forces CPU-addressable pixel conversion/readback and
        # makes the GUI thread responsible for the whole video pipeline.
        self.frame_ready.emit(QVideoFrame(frame))

    def _retry_priming(self, generation: int, position_ms: int) -> None:
        if generation != self._load_generation or not self._priming_video:
            return
        self.player.setPosition(position_ms)
        self.player.play()

    def _error_occurred(self, _error: QMediaPlayer.Error, message: str) -> None:
        if self._load_pending and not self._source_started:
            return
        self._emit_error(message or self.player.errorString() or "미디어 backend 오류")

    def _emit_error(self, message: str) -> None:
        self._load_pending = False
        self._source_started = False
        self._priming_video = False
        self._accept_video_frames = False
        self._set_status(PlaybackStatus.ERROR)
        self.error_occurred.emit(message)
