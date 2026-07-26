from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from church_presenter.domain.enums import (
    AudioAvailability,
    AudioSourceType,
    MediaType,
    PauseReason,
    PlaybackStatus,
    RepeatMode,
    SortField,
)
from church_presenter.domain.models import (
    AudioPlaybackRuntimeState,
    AudioPlaylist,
    FileItem,
    PlaylistItem,
)
from church_presenter.media.audio_controller import AudioPlaybackController
from church_presenter.media.playlist import YOUTUBE_URL_FILENAME, PlaylistService
from church_presenter.services.media_library_service import MediaLibraryCoordinator
from church_presenter.ui.panels.video_panel import format_media_time


class AudioPanel(QWidget):
    """Folder-backed background-music playlist with YouTube URL persistence."""

    folder_changed = Signal(str)
    settings_changed = Signal()
    status_changed = Signal(str)

    def __init__(
        self,
        controller: AudioPlaybackController,
        playlist_service: PlaylistService,
        folder: Path | None,
        sort_field: SortField,
        descending: bool,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.playlist_service = playlist_service
        self.folder = folder
        self.sort_field = sort_field
        self.descending = descending
        self._track_background = QColor(Qt.GlobalColor.blue)
        self._track_text = QColor(Qt.GlobalColor.black)
        self._track_active_text = QColor(Qt.GlobalColor.white)
        self._highlighted_item_id = ""
        self._last_runtime_notice = ""
        self._compact_mode = False
        self.library = MediaLibraryCoordinator()
        self.library.scanned.connect(self._scan_finished)
        self._build_ui()
        self._refresh_playlist()
        if folder:
            self.refresh_library()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.root_layout = layout
        toolbar = QHBoxLayout()
        self.toolbar_layout = toolbar
        self.folder_button = QPushButton("음악 폴더")
        self.folder_label = QLabel(str(self.folder or "선택되지 않음"))
        self.folder_label.setMinimumWidth(0)
        self.folder_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.folder_label.setToolTip(str(self.folder or ""))
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("파일명", SortField.NAME.value)
        self.sort_combo.addItem("수정 날짜", SortField.MODIFIED.value)
        self.sort_combo.setCurrentIndex(0 if self.sort_field is SortField.NAME else 1)
        self.descending_check = QCheckBox("내림차순")
        self.descending_check.setChecked(self.descending)
        self.refresh_button = QPushButton("새로고침")
        for widget in (
            self.folder_button,
            self.folder_label,
            self.sort_combo,
            self.descending_check,
            self.refresh_button,
        ):
            toolbar.addWidget(widget)
        toolbar.setStretch(1, 1)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.playlist_box = QWidget()
        playlist_layout = QVBoxLayout(self.playlist_box)
        playlist_layout.setContentsMargins(0, 0, 0, 0)
        source_actions = QHBoxLayout()
        self.youtube_add_button = QPushButton("YouTube URL 추가")
        self.fallback_button = QPushButton("대체 파일 지정")
        self.retry_button = QPushButton("상태 재확인")
        self.remove_youtube_button = QPushButton("URL 삭제")
        for widget in (
            self.youtube_add_button,
            self.fallback_button,
            self.retry_button,
            self.remove_youtube_button,
        ):
            source_actions.addWidget(widget)
        source_actions.addStretch()
        playlist_layout.addLayout(source_actions)
        self.playlist_caption = QLabel(
            f"폴더 재생목록 · 로컬 음악 + {YOUTUBE_URL_FILENAME}"
        )
        playlist_layout.addWidget(self.playlist_caption)
        self.playlist_list = QListWidget()
        self.playlist_list.setObjectName("AudioPlaylistList")
        self.playlist_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        playlist_layout.addWidget(self.playlist_list, 1)

        self.control_panel = QFrame()
        self.control_panel.setObjectName("AudioControlPanel")
        self.control_panel.setFrameShape(QFrame.Shape.StyledPanel)
        self.control_panel.setMinimumWidth(300)
        self.control_panel.setMaximumWidth(520)
        self.control_panel.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        self.player_layout = QVBoxLayout(self.control_panel)
        self.player_layout.setContentsMargins(10, 10, 10, 10)
        self.player_layout.setSpacing(8)

        self.player_title = QLabel("배경음악 제어")
        self.player_title.setProperty("role", "sectionTitle")
        self.track_summary_label = QLabel("선택한 곡 없음")
        self.track_summary_label.setObjectName("AudioTrackSummary")
        self.track_summary_label.setMinimumWidth(0)
        self.track_summary_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.playback_summary_label = QLabel("정지")
        self.playback_summary_label.setProperty("role", "secondary")
        self.player_layout.addWidget(self.player_title)
        self.player_layout.addWidget(self.track_summary_label)
        self.player_layout.addWidget(self.playback_summary_label)

        transport = QHBoxLayout()
        self.previous_button = self._transport_button("⏮", "이전 곡")
        self.play_button = self._transport_button("▶", "재생")
        self.play_button.setProperty("variant", "primary")
        self.pause_button = self._transport_button("⏸", "일시정지")
        self.stop_button = self._transport_button("■", "정지")
        self.next_button = self._transport_button("⏭", "다음 곡")
        for widget in (
            self.previous_button,
            self.play_button,
            self.pause_button,
            self.stop_button,
            self.next_button,
        ):
            transport.addWidget(widget)
        self.player_layout.addLayout(transport)

        seek_row = QHBoxLayout()
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.time_label = QLabel("00:00 / 00:00")
        seek_row.addWidget(self.seek_slider, 1)
        seek_row.addWidget(self.time_label)
        self.player_layout.addLayout(seek_row)

        self.options_layout = QGridLayout()
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(round(self.controller.runtime.volume * 100))
        self.mute_check = QCheckBox("음소거")
        self.mute_check.setChecked(self.controller.runtime.is_muted)
        self.repeat_combo = QComboBox()
        self.repeat_combo.addItem("반복 없음", RepeatMode.NONE.value)
        self.repeat_combo.addItem("한 곡 반복", RepeatMode.ONE.value)
        self.repeat_combo.addItem("전체 반복", RepeatMode.ALL.value)
        self.repeat_combo.setCurrentIndex(
            [RepeatMode.NONE, RepeatMode.ONE, RepeatMode.ALL].index(
                self.controller.playlist.repeat_mode
            )
        )
        self.volume_label = QLabel("볼륨")
        self.repeat_label = QLabel("반복")
        self.options_layout.addWidget(self.volume_label, 0, 0)
        self.options_layout.addWidget(self.volume_slider, 0, 1, 1, 2)
        self.options_layout.addWidget(self.mute_check, 0, 3)
        self.options_layout.addWidget(self.repeat_label, 1, 0)
        self.options_layout.addWidget(self.repeat_combo, 1, 1, 1, 3)
        self.options_layout.setColumnStretch(1, 1)
        self.player_layout.addLayout(self.options_layout)

        self.player_layout.addStretch()

        splitter.addWidget(self.playlist_box)
        splitter.addWidget(self.control_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([760, 420])
        layout.addWidget(splitter, 1)

        self.folder_button.clicked.connect(self.choose_folder)
        self.youtube_add_button.clicked.connect(self.add_youtube_url)
        self.fallback_button.clicked.connect(self.set_selected_fallback)
        self.retry_button.clicked.connect(self.retry_selected)
        self.remove_youtube_button.clicked.connect(self.remove_selected_youtube)
        self.refresh_button.clicked.connect(self.refresh_library)
        self.sort_combo.currentIndexChanged.connect(self._sort_changed)
        self.descending_check.toggled.connect(self._sort_changed)
        self.playlist_list.itemDoubleClicked.connect(self._play_item)
        self.playlist_list.currentRowChanged.connect(self._selection_changed)
        self.play_button.clicked.connect(self._play_selected_or_current)
        self.pause_button.clicked.connect(self.controller.pause)
        self.stop_button.clicked.connect(self.controller.stop)
        self.previous_button.clicked.connect(self.controller.previous)
        self.next_button.clicked.connect(self.controller.next)
        self.seek_slider.sliderMoved.connect(self.controller.seek)
        self.volume_slider.valueChanged.connect(self._volume_changed)
        self.mute_check.toggled.connect(self._mute_changed)
        self.repeat_combo.currentIndexChanged.connect(self._repeat_changed)
        self.controller.runtime_changed.connect(self._runtime_changed)
        self.controller.playlist_changed.connect(lambda _playlist: self._refresh_playlist())
        self.controller.track_changed.connect(self._track_changed)
        self.controller.error_occurred.connect(
            lambda message: self._set_status(f"오류: {message}")
        )
        self._runtime_changed(self.controller.runtime)

    def set_compact_mode(self, compact: bool) -> None:
        """Reflow audio controls for a shallow laptop-sized workspace."""
        if compact == self._compact_mode:
            return
        self._compact_mode = compact
        self.root_layout.setContentsMargins(*(6, 6, 6, 6) if compact else (9, 9, 9, 9))
        self.root_layout.setSpacing(6 if compact else 9)
        self.toolbar_layout.setSpacing(6 if compact else 9)
        self.control_panel.setMinimumWidth(240 if compact else 300)
        self.player_layout.setContentsMargins(*(6, 6, 6, 6) if compact else (10, 10, 10, 10))
        self.player_layout.setSpacing(3 if compact else 8)
        self.player_title.setVisible(not compact)
        self.playback_summary_label.setVisible(not compact)
        self.volume_label.setVisible(not compact)
        self.repeat_label.setVisible(not compact)
        self.folder_button.setText("음악 폴더" if not compact else "폴더")
        self.refresh_button.setText("새로고침" if not compact else "↻")
        self.youtube_add_button.setText("YouTube URL 추가" if not compact else "+ URL")
        self.fallback_button.setText("대체 파일 지정" if not compact else "대체")
        self.retry_button.setText("상태 재확인" if not compact else "재확인")
        self.remove_youtube_button.setText("URL 삭제" if not compact else "삭제")
        self.playlist_caption.setText(
            f"폴더 재생목록 · 로컬 음악 + {YOUTUBE_URL_FILENAME}"
            if not compact
            else "폴더 재생목록"
        )
        for widget in (
            self.volume_label,
            self.volume_slider,
            self.mute_check,
            self.repeat_label,
            self.repeat_combo,
        ):
            self.options_layout.removeWidget(widget)
        if compact:
            self.options_layout.addWidget(self.volume_slider, 0, 0, 1, 2)
            self.options_layout.addWidget(self.mute_check, 0, 2)
            self.options_layout.addWidget(self.repeat_combo, 0, 3)
        else:
            self.options_layout.addWidget(self.volume_label, 0, 0)
            self.options_layout.addWidget(self.volume_slider, 0, 1, 1, 2)
            self.options_layout.addWidget(self.mute_check, 0, 3)
            self.options_layout.addWidget(self.repeat_label, 1, 0)
            self.options_layout.addWidget(self.repeat_combo, 1, 1, 1, 3)
        self._runtime_changed(self.controller.runtime)

    @staticmethod
    def _transport_button(symbol: str, description: str) -> QPushButton:
        button = QPushButton(symbol)
        button.setToolTip(description)
        button.setAccessibleName(description)
        button.setMinimumWidth(44)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return button

    def set_playlist_theme(
        self,
        *,
        active_background: str,
        text: str,
        active_text: str,
    ) -> None:
        """Apply semantic theme colors to the current-track highlight."""
        self._track_background = QColor(active_background)
        self._track_text = QColor(text)
        self._track_active_text = QColor(active_text)
        self._refresh_playing_highlight(force=True)

    def choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "음악 폴더 선택", str(self.folder or Path.home())
        )
        if not selected:
            return
        self.folder = Path(selected).expanduser().resolve()
        self.folder_label.setText(selected)
        self.folder_label.setToolTip(selected)
        self.folder_changed.emit(selected)
        self._clear_for_folder_scan()
        self.refresh_library()

    def refresh_library(self) -> None:
        if self.folder is None:
            return
        self._set_status("폴더 재생목록을 확인하고 있습니다.")
        self.library.scan(self.folder, MediaType.AUDIO, self.sort_field, self.descending)

    def add_youtube_url(self) -> None:
        if self.folder is None:
            QMessageBox.warning(self, "YouTube URL", "음악 폴더를 먼저 선택하십시오.")
            return
        url, accepted = QInputDialog.getText(
            self,
            "YouTube URL 추가",
            "공개된 단일 YouTube 영상 URL:",
        )
        if not accepted or not url.strip():
            return
        existing_ids = {item.item_id for item in self.controller.playlist.items}
        try:
            item_id = self.controller.add_youtube_url(url)
            self._save_youtube_urls()
        except (OSError, ValueError) as error:
            if "item_id" in locals() and item_id not in existing_ids:
                index = self._find_item(item_id)
                if index is not None:
                    self.controller.remove(index)
            message = f"YouTube URL 저장 오류: {error}"
            self._set_status(message)
            QMessageBox.warning(self, "YouTube URL", message)
            return
        self._set_status(
            f"{YOUTUBE_URL_FILENAME}에 저장하고 메타데이터를 확인하고 있습니다."
        )
        self._select_item_id(item_id)

    def set_selected_fallback(self) -> None:
        row = self.playlist_list.currentRow()
        if not 0 <= row < len(self.controller.playlist.items):
            return
        item = self.controller.playlist.items[row]
        if item.source_type is not AudioSourceType.YOUTUBE:
            return
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "로컬 fallback 음악 선택",
            str(item.fallback_path.parent if item.fallback_path else self.folder),
            "Audio (*.mp3 *.wav *.m4a *.flac *.ogg)",
        )
        if not selected:
            return
        previous = item.fallback_path
        self.controller.set_fallback(row, Path(selected))
        try:
            self._save_youtube_urls()
        except OSError as error:
            self.controller.set_fallback(row, previous)
            self._set_status(f"fallback 저장 오류: {error}")

    def retry_selected(self) -> None:
        row = self.playlist_list.currentRow()
        if self.controller.retry_youtube(row):
            self._set_status("YouTube 상태를 다시 확인하고 있습니다.")

    def remove_selected_youtube(self) -> None:
        row = self.playlist_list.currentRow()
        if not 0 <= row < len(self.controller.playlist.items):
            return
        item = self.controller.playlist.items[row]
        if item.source_type is not AudioSourceType.YOUTUBE:
            return
        self.controller.remove(row)
        try:
            self._save_youtube_urls()
        except OSError as error:
            self._set_status(f"YouTube URL 삭제 저장 오류: {error}")

    def confirm_discard_changes(self) -> bool:
        """Folder playlists persist URL edits immediately and need no close prompt."""
        return True

    def _clear_for_folder_scan(self) -> None:
        repeat_mode = self.controller.playlist.repeat_mode
        self.controller.replace_playlist(
            AudioPlaylist(
                name=self.folder.name if self.folder else "폴더 재생목록",
                repeat_mode=repeat_mode,
            )
        )

    def _scan_finished(self, items: list[FileItem], error: str) -> None:
        if error:
            self._clear_for_folder_scan()
            self._set_status(f"음악 폴더 오류: {error}")
            return
        previous_by_path = {
            item.path: item
            for item in self.controller.playlist.items
            if item.source_type is AudioSourceType.LOCAL_FILE and item.path is not None
        }
        local_items = [
            PlaylistItem(
                item_id=str(record.path),
                path=record.path,
                title=record.path.stem,
                duration_ms=(
                    previous_by_path[record.path].duration_ms
                    if record.path in previous_by_path
                    else None
                ),
            )
            for record in items
        ]
        youtube_items: list[PlaylistItem] = []
        youtube_error = ""
        if self.folder is not None:
            try:
                youtube_items = self.playlist_service.load_youtube_items(self.folder)
            except (OSError, UnicodeError, ValueError, TypeError) as load_error:
                youtube_error = str(load_error)
        repeat_mode = self.controller.playlist.repeat_mode
        playlist = AudioPlaylist(
            name=self.folder.name if self.folder else "폴더 재생목록",
            items=[*local_items, *youtube_items],
            current_index=0 if local_items or youtube_items else None,
            repeat_mode=repeat_mode,
            is_modified=False,
        )
        self.controller.replace_playlist(playlist)
        if youtube_error:
            self._set_status(
                f"{YOUTUBE_URL_FILENAME} 오류 · 로컬 음악만 불러왔습니다: {youtube_error}"
            )
        else:
            self._set_status(
                f"폴더 재생목록 준비 완료 · 로컬 {len(local_items)}곡 · "
                f"YouTube {len(youtube_items)}개"
            )

    def _save_youtube_urls(self) -> None:
        if self.folder is None:
            raise OSError("음악 폴더가 선택되지 않았습니다.")
        self.playlist_service.save_youtube_items(
            self.controller.playlist.items,
            self.folder,
        )
        self.controller.playlist.is_modified = False

    def _refresh_playlist(self) -> None:
        selected_id = (
            str(self.playlist_list.currentItem().data(Qt.ItemDataRole.UserRole))
            if self.playlist_list.currentItem() is not None
            else None
        )
        current_id = (
            self.controller.playlist.current_item.item_id
            if self.controller.playlist.current_item
            else None
        )
        self.playlist_list.clear()
        for item in self.controller.playlist.items:
            source = "LOCAL" if item.source_type is AudioSourceType.LOCAL_FILE else "YOUTUBE"
            duration = (
                format_media_time(item.duration_ms) if item.duration_ms is not None else "--:--"
            )
            if item.source_type is AudioSourceType.LOCAL_FILE:
                state = "ready" if item.path is not None and item.path.is_file() else "missing"
            else:
                state = item.availability.value
            fallback = " · fallback" if item.fallback_path is not None else ""
            widget_item = QListWidgetItem(
                f"[{source}] {item.title} · {duration} · {state}{fallback}"
            )
            widget_item.setData(Qt.ItemDataRole.UserRole, item.item_id)
            widget_item.setToolTip(item.error_message or item.source)
            self.playlist_list.addItem(widget_item)
        self._select_item_id(selected_id or current_id or "")
        self._refresh_playing_highlight(force=True)
        self._update_action_states()

    def _play_item(self, item: QListWidgetItem) -> None:
        self.controller.play(self.playlist_list.row(item))

    def _play_selected_or_current(self) -> None:
        row = self.playlist_list.currentRow()
        self.controller.play(row if row >= 0 else None)

    def _runtime_changed(self, runtime: AudioPlaybackRuntimeState) -> None:
        status_labels = {
            PlaybackStatus.UNLOADED: "준비되지 않음",
            PlaybackStatus.PREPARING: "스트림 준비 중",
            PlaybackStatus.LOADING: "불러오는 중",
            PlaybackStatus.READY: "재생 준비 완료",
            PlaybackStatus.CUE: "재생 준비 완료",
            PlaybackStatus.LIVE_PAUSED: "일시정지",
            PlaybackStatus.PLAYING: "재생 중",
            PlaybackStatus.PAUSED: "일시정지",
            PlaybackStatus.BUFFERING: "버퍼링 중",
            PlaybackStatus.STOPPED: "정지",
            PlaybackStatus.ENDED: "재생 완료",
            PlaybackStatus.ERROR: "재생 오류",
        }
        status_text = status_labels[runtime.status]
        title = runtime.title or "선택한 곡 없음"
        self.track_summary_label.setText(
            f"{title} · {status_text}" if self._compact_mode else title
        )
        self.track_summary_label.setToolTip(runtime.source)
        self.playback_summary_label.setText(status_text)
        self.seek_slider.setRange(0, max(0, runtime.duration_ms))
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(runtime.position_ms)
        self.time_label.setText(
            f"{format_media_time(runtime.position_ms)} / "
            f"{format_media_time(runtime.duration_ms)}"
        )
        notice = ""
        if runtime.pause_reason is PauseReason.VIDEO:
            notice = "영상 재생으로 인해 배경음악이 일시정지되었습니다."
        elif runtime.status_message:
            notice = runtime.status_message
        if notice and notice != self._last_runtime_notice:
            self._set_status(notice)
        self._last_runtime_notice = notice
        self._refresh_playing_highlight()
        self._update_action_states()

    def _track_changed(self, index: int) -> None:
        if 0 <= index < self.playlist_list.count():
            self.playlist_list.setCurrentRow(
                index, QItemSelectionModel.SelectionFlag.ClearAndSelect
            )
        self._refresh_playlist()

    def _select_item_id(self, item_id: str) -> None:
        for index in range(self.playlist_list.count()):
            if self.playlist_list.item(index).data(Qt.ItemDataRole.UserRole) == item_id:
                self.playlist_list.setCurrentRow(index)
                return

    def _selection_changed(self, _row: int) -> None:
        self._refresh_playing_highlight()
        self._update_action_states()

    def _refresh_playing_highlight(self, *, force: bool = False) -> None:
        active_statuses = {
            PlaybackStatus.PREPARING,
            PlaybackStatus.LOADING,
            PlaybackStatus.READY,
            PlaybackStatus.CUE,
            PlaybackStatus.PLAYING,
            PlaybackStatus.PAUSED,
            PlaybackStatus.BUFFERING,
        }
        current = self.controller.playlist.current_item
        active_id = (
            current.item_id
            if current is not None and self.controller.runtime.status in active_statuses
            else ""
        )
        selected_item = self.playlist_list.currentItem()
        selected_active = (
            selected_item is not None
            and selected_item.data(Qt.ItemDataRole.UserRole) == active_id
        )
        if self.playlist_list.property("currentTrackSelected") != selected_active:
            self.playlist_list.setProperty("currentTrackSelected", selected_active)
            style = self.playlist_list.style()
            style.unpolish(self.playlist_list)
            style.polish(self.playlist_list)
        if not force and active_id == self._highlighted_item_id:
            return
        self._highlighted_item_id = active_id
        for index in range(self.playlist_list.count()):
            item = self.playlist_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == active_id:
                item.setBackground(self._track_background)
                item.setForeground(self._track_active_text)
            else:
                item.setBackground(Qt.GlobalColor.transparent)
                item.setForeground(self._track_text)

    def _set_status(self, message: str) -> None:
        self.status_changed.emit(message)

    def _find_item(self, item_id: str) -> int | None:
        return next(
            (
                index
                for index, item in enumerate(self.controller.playlist.items)
                if item.item_id == item_id
            ),
            None,
        )

    def _update_action_states(self) -> None:
        row = self.playlist_list.currentRow()
        item = (
            self.controller.playlist.items[row]
            if 0 <= row < len(self.controller.playlist.items)
            else None
        )
        youtube = item is not None and item.source_type is AudioSourceType.YOUTUBE
        self.fallback_button.setEnabled(youtube)
        self.remove_youtube_button.setEnabled(youtube)
        self.retry_button.setEnabled(
            youtube
            and item is not None
            and item.availability
            in {AudioAvailability.UNAVAILABLE, AudioAvailability.UNRESOLVED}
        )
        busy = self.controller.runtime.status in {
            PlaybackStatus.PREPARING,
            PlaybackStatus.LOADING,
        }
        self.play_button.setEnabled(bool(self.controller.playlist.items) and not busy)
        self.pause_button.setEnabled(
            self.controller.runtime.status
            in {PlaybackStatus.PLAYING, PlaybackStatus.BUFFERING}
        )
        self.stop_button.setEnabled(
            self.controller.runtime.status
            not in {PlaybackStatus.UNLOADED, PlaybackStatus.STOPPED}
        )

    def _sort_changed(self) -> None:
        self.sort_field = SortField(str(self.sort_combo.currentData()))
        self.descending = self.descending_check.isChecked()
        self.settings_changed.emit()
        self.refresh_library()

    def _volume_changed(self, value: int) -> None:
        self.controller.set_volume(value / 100)
        self.settings_changed.emit()

    def _mute_changed(self, muted: bool) -> None:
        self.controller.set_muted(muted)
        self.settings_changed.emit()

    def _repeat_changed(self) -> None:
        self.controller.set_repeat_mode(RepeatMode(str(self.repeat_combo.currentData())))
        self.settings_changed.emit()
