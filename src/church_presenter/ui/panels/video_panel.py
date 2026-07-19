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
    QSpinBox,
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

    def __init__(
        self,
        manager: VideoPlaybackManager,
        folder: Path | None,
        sort_field: SortField,
        descending: bool,
        volume: int,
        muted: bool,
        fade_duration_ms: int,
        last_selected_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.manager = manager
        self.folder = folder
        self.sort_field = sort_field
        self.descending = descending
        self.selected_path: Path | None = None
        self.last_selected_path = last_selected_path
        self._preview_ready = {
            ChannelRole.BROADCAST: False,
            ChannelRole.VENUE: False,
        }
        self._compact_mode = False
        self.library = MediaLibraryCoordinator()
        self.library.scanned.connect(self._scan_finished)
        self.setAcceptDrops(True)
        self._build_ui(volume, muted, fade_duration_ms)
        if folder:
            self.refresh()

    @property
    def target_role(self) -> ChannelRole:
        return ChannelRole(self.target_combo.currentData())

    def _build_ui(self, volume: int, muted: bool, fade_duration_ms: int) -> None:
        layout = QVBoxLayout(self)
        self.root_layout = layout
        toolbar = QHBoxLayout()
        self.toolbar_layout = toolbar
        folder_button = QPushButton("영상 폴더")
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
        refresh_button = QPushButton("새로고침")
        for widget in (
            folder_button,
            self.folder_label,
            self.sort_combo,
            self.descending_check,
            refresh_button,
        ):
            toolbar.addWidget(widget)
        toolbar.setStretch(1, 1)
        layout.addLayout(toolbar)

        content_layout = QHBoxLayout()
        self.content_layout = content_layout
        content_layout.setSpacing(10)
        library_layout = QVBoxLayout()
        self.library_layout = library_layout
        library_layout.setContentsMargins(0, 0, 0, 0)
        library_layout.setSpacing(6)
        self.file_list = QListWidget()
        self.file_list.setIconSize(QPixmap(160, 90).size())
        self.info_label = QLabel("영상 파일을 선택하면 실제 첫 프레임을 Preview로 준비합니다.")
        library_layout.addWidget(self.file_list, 1)
        library_layout.addWidget(self.info_label)
        content_layout.addLayout(library_layout, 1)

        self.control_panel = QFrame()
        self.control_panel.setObjectName("VideoControlPanel")
        self.control_panel.setFrameShape(QFrame.Shape.StyledPanel)
        self.control_panel.setMinimumWidth(240)
        self.control_panel.setMaximumWidth(640)
        self.control_panel.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        controls = QGridLayout(self.control_panel)
        self.controls_layout = controls
        controls.setContentsMargins(8, 8, 8, 8)
        controls.setHorizontalSpacing(6)
        controls.setVerticalSpacing(6)

        self.target_combo = QComboBox()
        self.target_combo.addItem("송출", ChannelRole.BROADCAST.value)
        self.target_combo.addItem("현장", ChannelRole.VENUE.value)
        cue_button = QPushButton("선택 채널 Preview Cue")
        cue_button.setProperty("variant", "primary")
        both_button = QPushButton("Send to Both")
        self.take_button = QPushButton("TAKE")
        self.take_both_button = QPushButton("TAKE BOTH")
        self.take_button.setProperty("variant", "take")
        self.take_both_button.setProperty("variant", "take")
        self.take_button.setEnabled(False)
        self.take_both_button.setEnabled(False)
        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")
        self.stop_button = QPushButton("Stop → BLACK")
        self.restart_button = QPushButton("처음으로")
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.time_label = QLabel("00:00 / 00:00")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(volume)
        self.mute_check = QCheckBox("음소거")
        self.mute_check.setChecked(muted)
        self.fade_spin = QSpinBox()
        self.fade_spin.setRange(0, 2000)
        self.fade_spin.setSuffix(" ms Fade")
        self.fade_spin.setValue(fade_duration_ms)
        self.status_label = QLabel("UNLOADED")
        self.status_label.setMinimumWidth(0)
        controls.addWidget(QLabel("제어 채널"), 0, 0)
        controls.addWidget(self.target_combo, 0, 1, 1, 3)
        controls.addWidget(cue_button, 1, 0, 1, 2)
        controls.addWidget(both_button, 1, 2, 1, 2)
        controls.addWidget(self.take_button, 2, 0, 1, 2)
        controls.addWidget(self.take_both_button, 2, 2, 1, 2)
        controls.addWidget(self.play_button, 3, 0)
        controls.addWidget(self.pause_button, 3, 1)
        controls.addWidget(self.stop_button, 3, 2)
        controls.addWidget(self.restart_button, 3, 3)
        controls.addWidget(self.seek_slider, 4, 0, 1, 3)
        controls.addWidget(self.time_label, 4, 3)
        controls.addWidget(QLabel("영상 볼륨"), 5, 0)
        controls.addWidget(self.volume_slider, 5, 1, 1, 2)
        controls.addWidget(self.mute_check, 5, 3)
        controls.addWidget(self.fade_spin, 6, 0)
        controls.addWidget(self.status_label, 6, 1, 1, 3)
        for column in range(4):
            controls.setColumnStretch(column, 1)
        controls.setRowStretch(7, 1)
        content_layout.addWidget(self.control_panel)
        layout.addLayout(content_layout, 1)

        folder_button.clicked.connect(self.choose_folder)
        refresh_button.clicked.connect(self.refresh)
        self.sort_combo.currentIndexChanged.connect(self._sort_changed)
        self.descending_check.toggled.connect(self._sort_changed)
        self.file_list.itemSelectionChanged.connect(self._selection_changed)
        cue_button.clicked.connect(self.cue_selected)
        both_button.clicked.connect(self.cue_both)
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
        self.fade_spin.valueChanged.connect(self.settings_changed)
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
        self.content_layout.setSpacing(6 if compact else 10)
        self.library_layout.setSpacing(4 if compact else 6)
        self.controls_layout.setContentsMargins(*control_margins)
        self.controls_layout.setHorizontalSpacing(4 if compact else 6)
        self.controls_layout.setVerticalSpacing(4 if compact else 6)
        self.file_list.setIconSize(QSize(128, 72) if compact else QSize(160, 90))
        self.info_label.setVisible(not compact)

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
        self.status_label.setText(f"{channel_label(role)} LOADING")
        self.manager.cue_preview(role, self.selected_path)

    def cue_both(self) -> None:
        if self.selected_path is None:
            return
        content = Content.video(self.selected_path)
        self._preview_ready[ChannelRole.BROADCAST] = False
        self._preview_ready[ChannelRole.VENUE] = False
        self._update_take_buttons()
        self.send_to_both_requested.emit(content, False)
        self.status_label.setText("송출 + 현장 LOADING")
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
        self.status_label.setText(
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
            return
        self.selected_path = Path(str(item.data(Qt.ItemDataRole.UserRole)))
        self.selection_changed.emit(str(self.selected_path))
        self.cue_selected()

    def _sort_changed(self) -> None:
        self.sort_field = SortField(str(self.sort_combo.currentData()))
        self.descending = self.descending_check.isChecked()
        self.settings_changed.emit()
        self.refresh()

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
        self.status_label.setText(
            f"{channel_label(role)} {runtime.status.value.upper()}{suffix}"
        )
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
