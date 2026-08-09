from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage, QPixmap
from PySide6.QtWidgets import (
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
    QVBoxLayout,
    QWidget,
)

from church_presenter.domain.enums import ChannelRole, MediaType, PlaybackStatus, SortField
from church_presenter.domain.models import Content, FileItem, VideoPlaybackRuntimeState
from church_presenter.media.base import MediaSource
from church_presenter.media.video_manager import VideoPlaybackManager
from church_presenter.media.youtube_resolver import validate_youtube_url
from church_presenter.services.feature_update_service import (
    FeatureUpdateResult,
    FeatureUpdateService,
)
from church_presenter.services.media_library_service import MediaLibraryCoordinator
from church_presenter.services.video_url_service import VIDEO_URL_FILENAME, VideoUrlService
from church_presenter.ui.labels import channel_label


def format_media_time(milliseconds: int) -> str:
    seconds = max(0, milliseconds) // 1000
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


class VideoPanel(QWidget):
    """Local-video library, cue, TAKE, and per-channel live controls."""

    preview_requested = Signal(object, object, bool)
    send_to_both_requested = Signal(object, bool)
    take_requested = Signal(object)
    take_both_requested = Signal()
    folder_changed = Signal(str)
    selection_changed = Signal(str)
    settings_changed = Signal()
    status_changed = Signal(str)

    def __init__(
        self,
        manager: VideoPlaybackManager,
        folder: Path | None,
        sort_field: SortField,
        descending: bool,
        volume: int,
        muted: bool,
        last_selected_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.manager = manager
        self.folder = folder
        del sort_field, descending  # Retained for settings and call-site compatibility.
        # A fixed newest-first order keeps recently added service media predictable.
        self.sort_field = SortField.MODIFIED
        self.descending = True
        self.selected_path: Path | None = None
        self.selected_source: MediaSource | None = None
        self.youtube_urls: list[str] = []
        self.video_url_service = VideoUrlService()
        self.last_selected_path = last_selected_path
        self._preview_ready = {
            ChannelRole.BROADCAST: False,
            ChannelRole.VENUE: False,
        }
        self._compact_mode = False
        self._last_runtime_notice = ""
        self.library = MediaLibraryCoordinator()
        self.library.scanned.connect(self._scan_finished)
        self.feature_updater = FeatureUpdateService(self)
        self.setAcceptDrops(True)
        self._build_ui(volume, muted)
        if folder:
            self.refresh()

    @property
    def target_role(self) -> ChannelRole:
        return ChannelRole(self.target_combo.currentData())

    def set_target_role(self, role: ChannelRole) -> None:
        """Select the channel controlled by the video panel."""
        index = self.target_combo.findData(role.value)
        if index >= 0:
            self.target_combo.setCurrentIndex(index)

    def _build_ui(self, volume: int, muted: bool) -> None:
        layout = QVBoxLayout(self)
        self.root_layout = layout
        toolbar = QHBoxLayout()
        self.toolbar_layout = toolbar
        self.folder_button = QPushButton("영상 폴더")
        self.folder_label = QLabel(str(self.folder or "선택되지 않음"))
        self.folder_label.setMinimumWidth(60)
        self.folder_label.setMaximumWidth(520)
        self.folder_label.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        self.folder_label.setToolTip(str(self.folder or ""))
        self.refresh_button = QPushButton("새로고침")
        self.url_add_button = QPushButton("URL 추가")
        self.url_remove_button = QPushButton("URL 삭제")
        self.url_remove_button.setEnabled(False)
        for widget in (self.folder_button, self.folder_label):
            toolbar.addWidget(widget)
        toolbar.addStretch(1)
        toolbar.addWidget(self.url_add_button)
        toolbar.addWidget(self.url_remove_button)
        toolbar.addWidget(self.refresh_button)

        self.target_toolbar = QHBoxLayout()
        self.target_toolbar.setContentsMargins(0, 0, 0, 0)
        self.feature_update_button = QPushButton("기능 최신화")
        self.feature_update_button.setToolTip(
            "현재 프로젝트 .venv에서 yt-dlp와 yt-dlp-ejs를 최신화합니다."
        )
        self.feature_update_button.setAccessibleName("YouTube 기능 최신화")
        self.target_toolbar.addWidget(self.feature_update_button)
        self.target_toolbar.addStretch(1)
        self.target_label = QLabel("제어 채널")
        self.target_combo = QComboBox()
        self.target_combo.addItem("송출", ChannelRole.BROADCAST.value)
        self.target_combo.addItem("현장", ChannelRole.VENUE.value)
        self.target_toolbar.addWidget(self.target_label)
        self.target_toolbar.addWidget(self.target_combo)

        content_layout = QHBoxLayout()
        self.content_layout = content_layout
        content_layout.setSpacing(10)
        library_layout = QVBoxLayout()
        self.library_layout = library_layout
        library_layout.setContentsMargins(0, 0, 0, 0)
        library_layout.setSpacing(6)
        self.file_list = QListWidget()
        self.file_list.setIconSize(QPixmap(160, 90).size())
        self.info_label = QLabel(
            "1 파일 선택  →  2 Preview Cue  →  3 TAKE  →  4 재생"
        )
        self.info_label.setProperty("role", "workflowHint")
        library_layout.addLayout(toolbar)
        library_layout.addWidget(self.file_list, 1)
        library_layout.addWidget(self.info_label)
        content_layout.addLayout(library_layout, 1)

        self.control_column = QWidget()
        self.control_column.setMinimumWidth(240)
        self.control_column.setMaximumWidth(640)
        self.control_column.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        self.control_column_layout = QVBoxLayout(self.control_column)
        self.control_column_layout.setContentsMargins(0, 0, 0, 0)
        self.control_column_layout.setSpacing(6)
        self.control_column_layout.addLayout(self.target_toolbar)

        self.control_panel = QFrame()
        self.control_panel.setObjectName("VideoControlPanel")
        self.control_panel.setFrameShape(QFrame.Shape.StyledPanel)
        self.control_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        controls = QGridLayout(self.control_panel)
        self.controls_layout = controls
        controls.setContentsMargins(8, 8, 8, 8)
        controls.setHorizontalSpacing(6)
        controls.setVerticalSpacing(6)

        self.cue_button = QPushButton("Preview Cue")
        self.cue_button.setProperty("variant", "secondary")
        self.cue_both_button = QPushButton("양쪽 Cue")
        self.cue_both_button.setProperty("variant", "primary")
        self.cue_button.setEnabled(False)
        self.cue_both_button.setEnabled(False)
        self.take_button = QPushButton("송출")
        self.take_button.setProperty("variant", "secondary")
        self.take_both_button = QPushButton("동시 송출")
        self.take_both_button.setProperty("variant", "take")
        self.take_button.setProperty("heightRole", "standard")
        self.take_both_button.setProperty("heightRole", "standard")
        self.take_button.setEnabled(False)
        self.take_both_button.setEnabled(False)
        for button, description in (
            (self.cue_button, "선택 채널에 Preview Cue"),
            (self.cue_both_button, "송출과 현장에 Preview Cue"),
            (self.take_button, "선택 채널 송출"),
            (self.take_both_button, "송출과 현장 동시 송출"),
        ):
            button.setToolTip(description)
            button.setAccessibleName(description)
            button.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Fixed,
            )
        self.action_panel = QWidget(self.control_panel)
        self.action_layout = QGridLayout(self.action_panel)
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.setHorizontalSpacing(6)
        self.action_layout.setVerticalSpacing(6)
        self.action_layout.addWidget(self.cue_button, 0, 0)
        self.action_layout.addWidget(self.cue_both_button, 0, 1)
        self.action_layout.addWidget(self.take_button, 1, 0)
        self.action_layout.addWidget(self.take_both_button, 1, 1)
        self.action_layout.setColumnStretch(0, 1)
        self.action_layout.setColumnStretch(1, 1)
        self.play_button = QPushButton("재생")
        self.pause_button = QPushButton("일시정지")
        self.stop_button = QPushButton("정지 → BLACK")
        self.restart_button = QPushButton("처음으로")
        for button, description in (
            (self.play_button, "영상 재생"),
            (self.pause_button, "영상 일시정지"),
            (self.stop_button, "영상 정지 후 BLACK"),
            (self.restart_button, "영상 처음으로"),
        ):
            button.setToolTip(description)
            button.setAccessibleName(description)
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setAccessibleName("영상 재생 위치")
        self.seek_slider.setToolTip("영상 재생 위치")
        self.seek_label = QLabel("위치")
        self.seek_label.hide()
        self.time_label = QLabel("00:00 / 00:00")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(volume)
        self.volume_slider.setAccessibleName("영상 볼륨")
        self.volume_slider.setToolTip("영상 볼륨")
        self.mute_check = QCheckBox("음소거")
        self.mute_check.setChecked(muted)
        self.volume_label = QLabel("영상 볼륨")
        controls.addWidget(self.action_panel, 0, 0, 1, 4)
        controls.addWidget(self.play_button, 1, 0)
        controls.addWidget(self.pause_button, 1, 1)
        controls.addWidget(self.stop_button, 1, 2)
        controls.addWidget(self.restart_button, 1, 3)
        controls.addWidget(self.seek_slider, 2, 0, 1, 3)
        controls.addWidget(self.time_label, 2, 3)
        controls.addWidget(self.volume_label, 3, 0)
        controls.addWidget(self.volume_slider, 3, 1, 1, 2)
        controls.addWidget(self.mute_check, 3, 3)
        for column in range(4):
            controls.setColumnStretch(column, 1)
        controls.setRowStretch(4, 1)
        self.control_column_layout.addWidget(self.control_panel, 1)
        content_layout.addWidget(self.control_column)
        layout.addLayout(content_layout, 1)

        self.folder_button.clicked.connect(self.choose_folder)
        self.refresh_button.clicked.connect(self.refresh)
        self.url_add_button.clicked.connect(self.add_youtube_url)
        self.url_remove_button.clicked.connect(self.remove_selected_youtube_url)
        self.feature_update_button.clicked.connect(self.update_features)
        self.feature_updater.started.connect(self._feature_update_started)
        self.feature_updater.finished.connect(self._feature_update_finished)
        self.file_list.itemSelectionChanged.connect(self._selection_changed)
        self.cue_button.clicked.connect(self.cue_selected)
        self.cue_both_button.clicked.connect(self.cue_both)
        self.take_button.clicked.connect(lambda: self.take_requested.emit(self.target_role))
        self.take_both_button.clicked.connect(self.take_both_requested)
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        self.play_button.clicked.connect(lambda: self.manager.play(self.target_role))
        self.pause_button.clicked.connect(lambda: self.manager.pause(self.target_role))
        self.stop_button.clicked.connect(lambda: self.manager.stop(self.target_role))
        self.restart_button.clicked.connect(lambda: self.manager.restart(self.target_role))
        self.seek_slider.sliderMoved.connect(
            lambda value: self.manager.seek(self.target_role, value)
        )
        self.volume_slider.valueChanged.connect(self._volume_changed)
        self.mute_check.toggled.connect(self._mute_changed)
        self.manager.runtime_changed.connect(self._runtime_changed)
        self._target_changed()

    def update_features(self) -> None:
        answer = QMessageBox.question(
            self,
            "기능 최신화",
            "현재 프로젝트 .venv에서 YouTube 재생 구성요소를 최신화합니다.\n\n"
            "yt-dlp와 yt-dlp-ejs가 업데이트되며 완료 후 앱을 다시 시작해야 "
            "합니다. 계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.feature_updater.start()
        except RuntimeError as error:
            QMessageBox.warning(self, "기능 최신화", str(error))

    def _feature_update_started(self) -> None:
        self.feature_update_button.setEnabled(False)
        self.feature_update_button.setText("최신화 중…")
        self._set_status("YouTube 기능 최신화 중…")

    def _feature_update_finished(self, result: FeatureUpdateResult) -> None:
        self.feature_update_button.setEnabled(True)
        self.feature_update_button.setText("기능 최신화")
        self._set_status(result.message.splitlines()[0])
        dialog = QMessageBox(self)
        dialog.setWindowTitle("기능 최신화")
        dialog.setIcon(
            QMessageBox.Icon.Information if result.success else QMessageBox.Icon.Critical
        )
        dialog.setText(result.message)
        if result.details:
            dialog.setDetailedText(result.details)
        dialog.exec()

    def set_compact_mode(self, compact: bool) -> None:
        """Reduce video-panel chrome for laptop-sized Controller windows."""
        if compact == self._compact_mode:
            return
        self._compact_mode = compact
        root_margins = (6, 6, 6, 6) if compact else (9, 9, 9, 9)
        control_margins = (6, 6, 6, 6) if compact else (8, 8, 8, 8)
        self.root_layout.setContentsMargins(*root_margins)
        self.root_layout.setSpacing(6 if compact else 9)
        self.toolbar_layout.setSpacing(6 if compact else 9)
        self.target_toolbar.setSpacing(6 if compact else 9)
        self.content_layout.setSpacing(6 if compact else 10)
        self.library_layout.setSpacing(4 if compact else 6)
        self.control_column_layout.setSpacing(4 if compact else 6)
        self.controls_layout.setContentsMargins(*control_margins)
        self.controls_layout.setHorizontalSpacing(4 if compact else 6)
        self.controls_layout.setVerticalSpacing(4 if compact else 6)
        self.action_layout.setHorizontalSpacing(4 if compact else 6)
        self.action_layout.setVerticalSpacing(4 if compact else 6)
        self.file_list.setIconSize(QSize(128, 72) if compact else QSize(160, 90))
        self.info_label.setVisible(not compact)
        self.folder_button.setText("폴더" if compact else "영상 폴더")
        self.folder_label.setMaximumWidth(120 if compact else 520)
        self.refresh_button.setText("↻" if compact else "새로고침")
        self.url_add_button.setText("+ URL" if compact else "URL 추가")
        self.url_remove_button.setText("- URL" if compact else "URL 삭제")
        self.play_button.setText("▶" if compact else "재생")
        self.pause_button.setText("⏸" if compact else "일시정지")
        self.stop_button.setText("■" if compact else "정지 → BLACK")
        self.restart_button.setText("↺" if compact else "처음으로")
        self.target_label.setVisible(not compact)
        self.volume_label.setText("볼륨" if compact else "영상 볼륨")
        self._arrange_controls(compact)

    def _arrange_controls(self, compact: bool) -> None:
        """Keep every video action usable when the lower workspace is shallow."""
        widgets = (
            self.action_panel,
            self.play_button,
            self.pause_button,
            self.stop_button,
            self.restart_button,
            self.seek_label,
            self.seek_slider,
            self.time_label,
            self.volume_label,
            self.volume_slider,
            self.mute_check,
        )
        for widget in widgets:
            self.controls_layout.removeWidget(widget)
        for row in range(6):
            self.controls_layout.setRowStretch(row, 0)

        if compact:
            self.time_label.hide()
            self.seek_label.show()
            self.volume_label.show()
            for column in range(6):
                self.controls_layout.setColumnStretch(column, 1)
            self.controls_layout.addWidget(self.action_panel, 0, 0, 1, 6)
            self.controls_layout.addWidget(self.play_button, 1, 0)
            self.controls_layout.addWidget(self.pause_button, 1, 1, 1, 2)
            self.controls_layout.addWidget(self.stop_button, 1, 3)
            self.controls_layout.addWidget(self.restart_button, 1, 4, 1, 2)
            self.controls_layout.addWidget(self.seek_label, 2, 0)
            self.controls_layout.addWidget(self.seek_slider, 2, 1, 1, 2)
            self.controls_layout.addWidget(self.volume_label, 2, 3)
            self.controls_layout.addWidget(self.volume_slider, 2, 4)
            self.controls_layout.addWidget(self.mute_check, 2, 5)
            self.controls_layout.setRowStretch(3, 1)
            return

        self.seek_label.hide()
        self.time_label.show()
        self.volume_label.show()
        for column in range(4):
            self.controls_layout.setColumnStretch(column, 1)
        self.controls_layout.setColumnStretch(4, 0)
        self.controls_layout.setColumnStretch(5, 0)
        self.controls_layout.addWidget(self.action_panel, 0, 0, 1, 4)
        self.controls_layout.addWidget(self.play_button, 1, 0)
        self.controls_layout.addWidget(self.pause_button, 1, 1)
        self.controls_layout.addWidget(self.stop_button, 1, 2)
        self.controls_layout.addWidget(self.restart_button, 1, 3)
        self.controls_layout.addWidget(self.seek_slider, 2, 0, 1, 3)
        self.controls_layout.addWidget(self.time_label, 2, 3)
        self.controls_layout.addWidget(self.volume_label, 3, 0)
        self.controls_layout.addWidget(self.volume_slider, 3, 1, 1, 2)
        self.controls_layout.addWidget(self.mute_check, 3, 3)
        self.controls_layout.setRowStretch(4, 1)

    def choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "영상 폴더 선택", str(self.folder or Path.home())
        )
        if not selected:
            return
        self.folder = Path(selected)
        self.folder_label.setText(selected)
        self.folder_label.setToolTip(selected)
        self.folder_changed.emit(selected)
        self.refresh()

    def refresh(self) -> None:
        if self.folder is None:
            return
        self.info_label.setText("영상 라이브러리 검색 중…")
        self.library.scan(self.folder, MediaType.VIDEO, self.sort_field, self.descending)

    def cue_selected(self) -> None:
        source = self.selected_source or self.selected_path
        if source is None:
            return
        role = self.target_role
        content = self._content_for_source(source)
        self._preview_ready[role] = False
        self._update_take_buttons()
        self.preview_requested.emit(role, content, False)
        self._set_status(f"{channel_label(role)} LOADING")
        self.manager.cue_preview(role, source)

    def cue_both(self) -> None:
        source = self.selected_source or self.selected_path
        if source is None:
            return
        content = self._content_for_source(source)
        self._preview_ready[ChannelRole.BROADCAST] = False
        self._preview_ready[ChannelRole.VENUE] = False
        self._update_take_buttons()
        self.send_to_both_requested.emit(content, False)
        self._set_status("송출 + 현장 LOADING")
        self.manager.cue_both(source)

    def preview_result(
        self,
        role: ChannelRole,
        path: str,
        image: QImage,
        error: str,
    ) -> None:
        item = self._item_for_source(path)
        if item is not None:
            if error:
                item.setText(f"⚠ {self._display_name(path)}\n{error}")
            elif not image.isNull():
                runtime = self.manager.preview_runtime(role)
                size_mb = int(item.data(Qt.ItemDataRole.UserRole + 1) or 0) / (1024 * 1024)
                size = f" · {size_mb:.1f} MB" if not self._is_url(path) else ""
                item.setText(
                    f"{self._display_name(path)}\n{format_media_time(runtime.duration_ms)} · "
                    f"{image.width()}x{image.height()}{size} · CUE"
                )
                item.setIcon(
                    QPixmap.fromImage(image).scaled(
                        160,
                        90,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        self._preview_ready[role] = not error and not image.isNull()
        self._update_take_buttons()
        self._set_status(
            f"{channel_label(role)} ERROR · {error}"
            if error
            else f"{channel_label(role)} CUE · TAKE 후에도 자동 재생하지 않습니다."
        )

    def invalidate_preview(self, role: ChannelRole) -> None:
        """Disable video TAKE when another content type replaces Preview."""
        self._preview_ready[role] = False
        self._update_take_buttons()

    def _scan_finished(self, items: list[FileItem], error: str) -> None:
        previous_source = self.selected_source
        self.file_list.clear()
        if error:
            self.info_label.setText(f"영상 라이브러리 오류: {error}")
            return
        for record in items:
            size_mb = record.file_size / (1024 * 1024)
            item = QListWidgetItem(f"{record.display_name}\n{size_mb:.1f} MB · 코덱 확인 전")
            item.setData(Qt.ItemDataRole.UserRole, str(record.path))
            item.setData(Qt.ItemDataRole.UserRole + 1, record.file_size)
            item.setData(Qt.ItemDataRole.UserRole + 2, "local")
            self.file_list.addItem(item)
        url_error = ""
        self.youtube_urls = []
        if self.folder is not None:
            try:
                self.youtube_urls = self.video_url_service.load(self.folder)
            except (OSError, UnicodeError, TypeError, ValueError) as load_error:
                url_error = str(load_error)
        for url in self.youtube_urls:
            self._append_youtube_item(url)
        self.info_label.setText(
            f"영상 로컬 {len(items)}개 · YouTube {len(self.youtube_urls)}개 · "
            "썸네일은 Cue 시 실제 프레임으로 갱신됩니다."
        )
        if url_error:
            self.info_label.setText(f"{VIDEO_URL_FILENAME} 오류: {url_error}")
        if previous_source is not None and self.select_source(previous_source):
            self.last_selected_path = None
            return
        if self.last_selected_path is not None:
            restored = self._item_for_path(self.last_selected_path)
            self.last_selected_path = None
            if restored is not None:
                self.file_list.setCurrentItem(restored)

    def _selection_changed(self) -> None:
        item = self.file_list.currentItem()
        if item is None:
            self.selected_path = None
            self.selected_source = None
            self._update_cue_buttons()
            return
        source_value = str(item.data(Qt.ItemDataRole.UserRole))
        is_url = item.data(Qt.ItemDataRole.UserRole + 2) == "youtube"
        self.selected_source = source_value if is_url else Path(source_value)
        self.selected_path = None if is_url else Path(source_value)
        self.selection_changed.emit(source_value)
        self._update_cue_buttons()
        self._set_status(
            f"{self._display_name(source_value)} 선택 · 채널을 확인하고 Preview Cue를 누르십시오."
        )

    def _runtime_changed(self, role: ChannelRole, runtime: VideoPlaybackRuntimeState) -> None:
        if role is not self.target_role:
            return
        self.seek_slider.setRange(0, max(0, runtime.duration_ms))
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(runtime.position_ms)
        self.time_label.setText(
            f"{format_media_time(runtime.position_ms)} / {format_media_time(runtime.duration_ms)}"
        )
        suffix = f" · {runtime.error_message}" if runtime.error_message else ""
        notice = f"{channel_label(role)} {runtime.status.value.upper()}{suffix}"
        if notice != self._last_runtime_notice:
            self._last_runtime_notice = notice
            self._set_status(notice)
        self._update_playback_controls(runtime)

    def _target_changed(self) -> None:
        self._update_take_buttons()
        self._runtime_changed(self.target_role, self.manager.runtime(self.target_role))

    def _update_playback_controls(
        self, runtime: VideoPlaybackRuntimeState | None = None
    ) -> None:
        runtime = runtime or self.manager.runtime(self.target_role)
        can_control = runtime.path is not None and runtime.status in {
            PlaybackStatus.LIVE_PAUSED,
            PlaybackStatus.PLAYING,
            PlaybackStatus.PAUSED,
        }
        self.play_button.setEnabled(
            can_control
            and runtime.status in {PlaybackStatus.LIVE_PAUSED, PlaybackStatus.PAUSED}
        )
        self.pause_button.setEnabled(can_control and runtime.status is PlaybackStatus.PLAYING)
        self.stop_button.setEnabled(can_control)
        self.restart_button.setEnabled(can_control)
        self.seek_slider.setEnabled(can_control)

    def _volume_changed(self, value: int) -> None:
        self.manager.set_volume(value / 100)
        self.settings_changed.emit()

    def _mute_changed(self, muted: bool) -> None:
        self.manager.set_muted(muted)
        self.settings_changed.emit()

    def _item_for_path(self, path: Path) -> QListWidgetItem | None:
        return self._item_for_source(str(path.expanduser().resolve()))

    def _item_for_source(self, source: str) -> QListWidgetItem | None:
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            if str(item.data(Qt.ItemDataRole.UserRole)) == source:
                return item
        return None

    def select_source(self, source: MediaSource) -> bool:
        """Select a saved source for subsequent operator navigation without cueing it."""
        if isinstance(source, str):
            try:
                selected_url = validate_youtube_url(source)
            except ValueError:
                return False
            selected_source: MediaSource = selected_url
            item = self._item_for_source(selected_url)
            if item is None:
                self._append_youtube_item(selected_url)
                item = self._item_for_source(selected_url)
        else:
            selected_source = source.expanduser().resolve()
            if not selected_source.is_file():
                return False
            item = self._item_for_path(selected_source)
            if item is None:
                item = QListWidgetItem(selected_source.name)
                item.setData(Qt.ItemDataRole.UserRole, str(selected_source))
                item.setData(Qt.ItemDataRole.UserRole + 2, "local")
                item.setToolTip(str(selected_source))
                self.file_list.addItem(item)
        if item is None:
            return False
        self.file_list.blockSignals(True)
        self.file_list.setCurrentItem(item)
        self.file_list.blockSignals(False)
        self.selected_source = selected_source
        self.selected_path = selected_source if isinstance(selected_source, Path) else None
        self.selection_changed.emit(str(selected_source))
        self._update_cue_buttons()
        self._set_status(
            f"{self._display_name(str(selected_source))} 선택 · "
            "채널을 확인하고 Preview Cue를 누르십시오."
        )
        return True

    def _update_take_buttons(self) -> None:
        self.take_button.setEnabled(self._preview_ready[self.target_role])
        self.take_both_button.setEnabled(all(self._preview_ready.values()))

    def _update_cue_buttons(self) -> None:
        source = self.selected_source or self.selected_path
        has_selection = source is not None and (
            isinstance(source, str) or source.is_file()
        )
        self.cue_button.setEnabled(has_selection)
        self.cue_both_button.setEnabled(has_selection)
        self.url_remove_button.setEnabled(isinstance(self.selected_source, str))

    def add_youtube_url(self) -> None:
        if self.folder is None:
            QMessageBox.warning(self, "영상 URL", "영상 폴더를 먼저 선택하십시오.")
            return
        raw, accepted = QInputDialog.getText(self, "YouTube 영상 URL", "URL")
        if not accepted or not raw.strip():
            return
        try:
            normalized = validate_youtube_url(raw)
            destination = self.video_url_service.save(
                self.folder,
                [*self.youtube_urls, normalized],
            )
            self.youtube_urls = self.video_url_service.load(self.folder)
        except (OSError, UnicodeError, TypeError, ValueError) as error:
            QMessageBox.warning(self, "영상 URL", str(error))
            return
        self._reload_youtube_items()
        selected = self._item_for_source(normalized)
        if selected is not None:
            self.file_list.setCurrentItem(selected)
        self._set_status(f"{destination.name}에 YouTube 영상 URL을 저장했습니다.")

    def remove_selected_youtube_url(self) -> None:
        if self.folder is None or not isinstance(self.selected_source, str):
            return
        selected = self.selected_source
        try:
            self.video_url_service.save(
                self.folder,
                [url for url in self.youtube_urls if url != selected],
            )
        except (OSError, UnicodeError, TypeError, ValueError) as error:
            QMessageBox.warning(self, "영상 URL", str(error))
            return
        self.youtube_urls = [url for url in self.youtube_urls if url != selected]
        self.selected_source = None
        self.selected_path = None
        self._reload_youtube_items()
        self._update_cue_buttons()

    def _reload_youtube_items(self) -> None:
        for index in reversed(range(self.file_list.count())):
            item = self.file_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole + 2) == "youtube":
                self.file_list.takeItem(index)
        for url in self.youtube_urls:
            self._append_youtube_item(url)

    def _append_youtube_item(self, url: str) -> None:
        item = QListWidgetItem(f"[YOUTUBE] {self._display_name(url)}\nURL · Cue 전")
        item.setData(Qt.ItemDataRole.UserRole, url)
        item.setData(Qt.ItemDataRole.UserRole + 1, 0)
        item.setData(Qt.ItemDataRole.UserRole + 2, "youtube")
        item.setToolTip(url)
        self.file_list.addItem(item)

    @staticmethod
    def _content_for_source(source: MediaSource) -> Content:
        return Content.youtube_video(source) if isinstance(source, str) else Content.video(source)

    @staticmethod
    def _is_url(source: str) -> bool:
        return source.startswith(("https://", "http://"))

    @classmethod
    def _display_name(cls, source: str) -> str:
        if cls._is_url(source):
            return f"YouTube · {source}"
        return Path(source).name

    def _set_status(self, message: str) -> None:
        self.status_changed.emit(message)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if any(
            Path(url.toLocalFile()).suffix.lower() in {".mp4", ".mov", ".mkv", ".avi"}
            for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        valid = [path for path in paths if path.suffix.lower() in {".mp4", ".mov", ".mkv", ".avi"}]
        if not valid:
            return
        path = valid[0].resolve()
        self.selected_source = path
        self.selected_path = path
        if self._item_for_path(path) is None:
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.file_list.addItem(item)
        selected_item = self._item_for_path(path)
        if selected_item is not None:
            self.file_list.setCurrentItem(selected_item)
        event.acceptProposedAction()
