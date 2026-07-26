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
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from church_presenter.domain.enums import ChannelRole, MediaType, PlaybackStatus, SortField
from church_presenter.domain.models import Content, FileItem, VideoPlaybackRuntimeState
from church_presenter.media.video_manager import VideoPlaybackManager
from church_presenter.services.media_library_service import MediaLibraryCoordinator
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
        self.last_selected_path = last_selected_path
        self._preview_ready = {
            ChannelRole.BROADCAST: False,
            ChannelRole.VENUE: False,
        }
        self._compact_mode = False
        self._last_runtime_notice = ""
        self.library = MediaLibraryCoordinator()
        self.library.scanned.connect(self._scan_finished)
        self.setAcceptDrops(True)
        self._build_ui(volume, muted)
        if folder:
            self.refresh()

    @property
    def target_role(self) -> ChannelRole:
        return ChannelRole(self.target_combo.currentData())

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
        for widget in (self.folder_button, self.folder_label):
            toolbar.addWidget(widget)
        toolbar.addStretch(1)
        toolbar.addWidget(self.refresh_button)

        self.target_toolbar = QHBoxLayout()
        self.target_toolbar.setContentsMargins(0, 0, 0, 0)
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
        self.take_button = QPushButton("TAKE")
        self.take_button.setProperty("variant", "secondary")
        self.take_both_button = QPushButton("TAKE BOTH")
        self.take_both_button.setProperty("variant", "take")
        self.take_button.setProperty("heightRole", "standard")
        self.take_both_button.setProperty("heightRole", "standard")
        self.take_button.setEnabled(False)
        self.take_both_button.setEnabled(False)
        for button, description in (
            (self.cue_button, "선택 채널에 Preview Cue"),
            (self.cue_both_button, "송출과 현장에 Preview Cue"),
            (self.take_button, "선택 채널 TAKE"),
            (self.take_both_button, "송출과 현장 TAKE BOTH"),
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
        if self.selected_path is None:
            return
        role = self.target_role
        content = Content.video(self.selected_path)
        self._preview_ready[role] = False
        self._update_take_buttons()
        self.preview_requested.emit(role, content, False)
        self._set_status(f"{channel_label(role)} LOADING")
        self.manager.cue_preview(role, self.selected_path)

    def cue_both(self) -> None:
        if self.selected_path is None:
            return
        content = Content.video(self.selected_path)
        self._preview_ready[ChannelRole.BROADCAST] = False
        self._preview_ready[ChannelRole.VENUE] = False
        self._update_take_buttons()
        self.send_to_both_requested.emit(content, False)
        self._set_status("송출 + 현장 LOADING")
        self.manager.cue_both(self.selected_path)

    def preview_result(
        self,
        role: ChannelRole,
        path: str,
        image: QImage,
        error: str,
    ) -> None:
        item = self._item_for_path(Path(path))
        if item is not None:
            if error:
                item.setText(f"⚠ {Path(path).name}\n{error}")
            elif not image.isNull():
                runtime = self.manager.preview_runtime(role)
                size_mb = int(item.data(Qt.ItemDataRole.UserRole + 1) or 0) / (1024 * 1024)
                item.setText(
                    f"{Path(path).name}\n{format_media_time(runtime.duration_ms)} · "
                    f"{image.width()}x{image.height()} · {size_mb:.1f} MB · CUE"
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
        self.file_list.clear()
        if error:
            self.info_label.setText(f"영상 라이브러리 오류: {error}")
            return
        for record in items:
            size_mb = record.file_size / (1024 * 1024)
            item = QListWidgetItem(f"{record.display_name}\n{size_mb:.1f} MB · 코덱 확인 전")
            item.setData(Qt.ItemDataRole.UserRole, str(record.path))
            item.setData(Qt.ItemDataRole.UserRole + 1, record.file_size)
            self.file_list.addItem(item)
        self.info_label.setText(
            f"영상 {len(items)}개 · 썸네일은 Cue 시 실제 프레임으로 갱신됩니다."
        )
        if self.last_selected_path is not None:
            restored = self._item_for_path(self.last_selected_path)
            self.last_selected_path = None
            if restored is not None:
                self.file_list.setCurrentItem(restored)

    def _selection_changed(self) -> None:
        item = self.file_list.currentItem()
        if item is None:
            self.selected_path = None
            self._update_cue_buttons()
            return
        self.selected_path = Path(str(item.data(Qt.ItemDataRole.UserRole)))
        self.selection_changed.emit(str(self.selected_path))
        self._update_cue_buttons()
        self._set_status(
            f"{self.selected_path.name} 선택 · 채널을 확인하고 Preview Cue를 누르십시오."
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
        target = path.expanduser().resolve()
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            if Path(str(item.data(Qt.ItemDataRole.UserRole))).expanduser().resolve() == target:
                return item
        return None

    def _update_take_buttons(self) -> None:
        self.take_button.setEnabled(self._preview_ready[self.target_role])
        self.take_both_button.setEnabled(all(self._preview_ready.values()))

    def _update_cue_buttons(self) -> None:
        has_selection = self.selected_path is not None and self.selected_path.is_file()
        self.cue_button.setEnabled(has_selection)
        self.cue_both_button.setEnabled(has_selection)

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
        self.selected_path = path
        if self._item_for_path(path) is None:
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.file_list.addItem(item)
        selected_item = self._item_for_path(path)
        if selected_item is not None:
            self.file_list.setCurrentItem(selected_item)
        event.acceptProposedAction()
