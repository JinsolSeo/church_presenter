from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from church_presenter.domain.enums import MediaType, PauseReason, RepeatMode, SortField
from church_presenter.domain.models import AudioPlaybackRuntimeState, FileItem
from church_presenter.media.audio_controller import AudioPlaybackController
from church_presenter.media.playlist import PlaylistService
from church_presenter.services.media_library_service import MediaLibraryCoordinator
from church_presenter.ui.panels.video_panel import format_media_time

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}


class AudioPanel(QWidget):
    """Global background-music library and persistent ordered playlist."""

    folder_changed = Signal(str)
    playlist_path_changed = Signal(str)
    settings_changed = Signal()

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
        self.playlist_path: Path | None = None
        self.library = MediaLibraryCoordinator()
        self.library.scanned.connect(self._scan_finished)
        self._reordering = False
        self.setAcceptDrops(True)
        self._build_ui()
        self._refresh_playlist()
        if folder:
            self.refresh_library()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        folder_button = QPushButton("음악 폴더")
        self.folder_label = QLabel(str(self.folder or "선택되지 않음"))
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
        layout.addLayout(toolbar)

        splitter = QSplitter()
        library_box = QWidget()
        library_layout = QVBoxLayout(library_box)
        library_layout.addWidget(QLabel("음악 라이브러리 · 더블클릭으로 추가"))
        self.library_list = QListWidget()
        self.library_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        library_layout.addWidget(self.library_list)
        playlist_box = QWidget()
        playlist_layout = QVBoxLayout(playlist_box)
        playlist_layout.addWidget(QLabel("재생목록 · 드래그로 순서 변경"))
        self.playlist_list = QListWidget()
        self.playlist_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.playlist_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.playlist_list.setDropIndicatorShown(True)
        playlist_layout.addWidget(self.playlist_list)
        splitter.addWidget(library_box)
        splitter.addWidget(playlist_box)
        layout.addWidget(splitter, 1)

        edit_actions = QHBoxLayout()
        add_button = QPushButton("선택 추가")
        remove_button = QPushButton("선택 제거")
        clear_button = QPushButton("전체 비우기")
        load_button = QPushButton("재생목록 불러오기")
        save_button = QPushButton("저장")
        save_as_button = QPushButton("다른 이름으로 저장")
        for widget in (
            add_button,
            remove_button,
            clear_button,
            load_button,
            save_button,
            save_as_button,
        ):
            edit_actions.addWidget(widget)
        layout.addLayout(edit_actions)

        controls = QGridLayout()
        previous_button = QPushButton("이전 곡")
        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")
        self.stop_button = QPushButton("Stop")
        next_button = QPushButton("다음 곡")
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.time_label = QLabel("00:00 / 00:00")
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
        self.status_label = QLabel("배경음악 정지")
        self.status_label.setWordWrap(True)
        for column, widget in enumerate(
            (previous_button, self.play_button, self.pause_button, self.stop_button, next_button)
        ):
            controls.addWidget(widget, 0, column)
        controls.addWidget(self.seek_slider, 1, 0, 1, 4)
        controls.addWidget(self.time_label, 1, 4)
        controls.addWidget(QLabel("음악 볼륨"), 2, 0)
        controls.addWidget(self.volume_slider, 2, 1, 1, 2)
        controls.addWidget(self.mute_check, 2, 3)
        controls.addWidget(self.repeat_combo, 2, 4)
        controls.addWidget(self.status_label, 3, 0, 1, 5)
        layout.addLayout(controls)

        folder_button.clicked.connect(self.choose_folder)
        refresh_button.clicked.connect(self.refresh_library)
        self.sort_combo.currentIndexChanged.connect(self._sort_changed)
        self.descending_check.toggled.connect(self._sort_changed)
        self.library_list.itemDoubleClicked.connect(lambda _item: self.add_selected())
        add_button.clicked.connect(self.add_selected)
        remove_button.clicked.connect(self.remove_selected)
        clear_button.clicked.connect(self.controller.clear)
        load_button.clicked.connect(self.choose_playlist)
        save_button.clicked.connect(self.save)
        save_as_button.clicked.connect(self.save_as)
        self.playlist_list.itemDoubleClicked.connect(self._play_item)
        self.playlist_list.model().rowsMoved.connect(self._rows_moved)
        self.play_button.clicked.connect(self._play_selected_or_current)
        self.pause_button.clicked.connect(self.controller.pause)
        self.stop_button.clicked.connect(self.controller.stop)
        previous_button.clicked.connect(self.controller.previous)
        next_button.clicked.connect(self.controller.next)
        self.seek_slider.sliderMoved.connect(self.controller.seek)
        self.volume_slider.valueChanged.connect(self._volume_changed)
        self.mute_check.toggled.connect(self._mute_changed)
        self.repeat_combo.currentIndexChanged.connect(self._repeat_changed)
        self.controller.runtime_changed.connect(self._runtime_changed)
        self.controller.playlist_changed.connect(lambda _playlist: self._refresh_playlist())
        self.controller.track_changed.connect(self._track_changed)
        self.controller.error_occurred.connect(
            lambda message: self.status_label.setText(f"오류: {message}")
        )
        self._runtime_changed(self.controller.runtime)

    def choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "음악 폴더 선택", str(self.folder or Path.home())
        )
        if not selected:
            return
        self.folder = Path(selected)
        self.folder_label.setText(selected)
        self.folder_changed.emit(selected)
        self.refresh_library()

    def refresh_library(self) -> None:
        if self.folder is None:
            return
        self.library.scan(self.folder, MediaType.AUDIO, self.sort_field, self.descending)

    def add_selected(self) -> None:
        paths = [
            Path(str(item.data(Qt.ItemDataRole.UserRole)))
            for item in self.library_list.selectedItems()
        ]
        self.controller.add_paths(paths)

    def remove_selected(self) -> None:
        rows = sorted(
            {self.playlist_list.row(item) for item in self.playlist_list.selectedItems()},
            reverse=True,
        )
        for row in rows:
            self.controller.remove(row)

    def choose_playlist(self) -> None:
        if not self.confirm_discard_changes():
            return
        selected, _ = QFileDialog.getOpenFileName(
            self, "재생목록 불러오기", str(self.folder or Path.home()), "JSON (*.json)"
        )
        if selected:
            try:
                self.load_playlist(Path(selected))
            except (OSError, UnicodeError, ValueError, TypeError) as error:
                self.status_label.setText(f"재생목록 불러오기 오류: {error}")
                QMessageBox.warning(self, "재생목록 오류", self.status_label.text())

    def load_playlist(self, path: Path) -> None:
        playlist = self.playlist_service.load(path)
        self.controller.replace_playlist(playlist)
        self.playlist_path = path.resolve()
        self.playlist_path_changed.emit(str(self.playlist_path))

    def save(self) -> None:
        if self.playlist_path is None:
            self.save_as()
            return
        self.save_playlist(self.playlist_path)

    def save_as(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self, "재생목록 저장", str(self.folder or Path.home()), "JSON (*.json)"
        )
        if selected:
            path = Path(selected)
            if path.suffix.lower() != ".json":
                path = path.with_suffix(".json")
            self.save_playlist(path)

    def save_playlist(self, path: Path) -> None:
        try:
            self.playlist_service.save(self.controller.playlist, path)
        except OSError as error:
            self.status_label.setText(f"재생목록 저장 오류: {error}")
            QMessageBox.warning(self, "재생목록 저장", self.status_label.text())
            return
        self.playlist_path = path.resolve()
        self.playlist_path_changed.emit(str(self.playlist_path))
        self._refresh_playlist()

    def confirm_discard_changes(self) -> bool:
        if not self.controller.playlist.is_modified:
            return True
        answer = QMessageBox.question(
            self,
            "저장하지 않은 재생목록",
            "재생목록 변경사항을 저장하지 않고 종료하시겠습니까?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer is QMessageBox.StandardButton.Discard

    def _scan_finished(self, items: list[FileItem], error: str) -> None:
        self.library_list.clear()
        if error:
            self.status_label.setText(f"음악 라이브러리 오류: {error}")
            return
        for record in items:
            item = QListWidgetItem(
                f"{record.display_name} · {record.file_size / (1024 * 1024):.1f} MB"
            )
            item.setData(Qt.ItemDataRole.UserRole, str(record.path))
            item.setData(Qt.ItemDataRole.UserRole + 1, record.file_size)
            self.library_list.addItem(item)

    def _refresh_playlist(self) -> None:
        current_id = (
            self.controller.playlist.current_item.item_id
            if self.controller.playlist.current_item
            else None
        )
        self._reordering = True
        self.playlist_list.clear()
        for item in self.controller.playlist.items:
            prefix = "▶ " if item.item_id == current_id else ""
            suffix = "" if item.path.is_file() else " · ⚠ 파일 없음"
            widget_item = QListWidgetItem(f"{prefix}{item.title}{suffix}")
            widget_item.setData(Qt.ItemDataRole.UserRole, item.item_id)
            self.playlist_list.addItem(widget_item)
        self._reordering = False

    def _rows_moved(
        self,
        _source_parent: QModelIndex,
        _source_start: int,
        _source_end: int,
        _destination_parent: QModelIndex,
        _destination_row: int,
    ) -> None:
        if self._reordering:
            return
        by_id = {item.item_id: item for item in self.controller.playlist.items}
        current_id = (
            self.controller.playlist.current_item.item_id
            if self.controller.playlist.current_item
            else None
        )
        ordered_ids = [
            str(self.playlist_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.playlist_list.count())
        ]
        self.controller.playlist.items = [by_id[item_id] for item_id in ordered_ids]
        if current_id is not None:
            self.controller.playlist.current_index = ordered_ids.index(current_id)
        self.controller.playlist.is_modified = True
        self.controller.playlist_changed.emit(self.controller.playlist)

    def _play_item(self, item: QListWidgetItem) -> None:
        self.controller.play(self.playlist_list.row(item))

    def _play_selected_or_current(self) -> None:
        row = self.playlist_list.currentRow()
        self.controller.play(row if row >= 0 else None)

    def _runtime_changed(self, runtime: AudioPlaybackRuntimeState) -> None:
        self.seek_slider.setRange(0, max(0, runtime.duration_ms))
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(runtime.position_ms)
        self.time_label.setText(
            f"{format_media_time(runtime.position_ms)} / {format_media_time(runtime.duration_ms)}"
        )
        if runtime.path is not None and runtime.duration_ms > 0:
            for index in range(self.library_list.count()):
                item = self.library_list.item(index)
                if Path(str(item.data(Qt.ItemDataRole.UserRole))) == runtime.path:
                    size_mb = int(item.data(Qt.ItemDataRole.UserRole + 1) or 0) / (1024 * 1024)
                    item.setText(
                        f"{runtime.path.name} · {format_media_time(runtime.duration_ms)} · "
                        f"{size_mb:.1f} MB"
                    )
                    break
        if runtime.pause_reason is PauseReason.VIDEO:
            self.status_label.setText("영상 재생으로 인해 배경음악이 일시정지되었습니다.")
        else:
            title = (
                self.controller.playlist.current_item.title
                if self.controller.playlist.current_item
                else "없음"
            )
            self.status_label.setText(f"{runtime.status.value.upper()} · 현재 곡: {title}")

    def _track_changed(self, index: int) -> None:
        if 0 <= index < self.playlist_list.count():
            self.playlist_list.setCurrentRow(
                index, QItemSelectionModel.SelectionFlag.ClearAndSelect
            )
        self._refresh_playlist()

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

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if any(
            Path(url.toLocalFile()).suffix.lower() in AUDIO_EXTENSIONS
            for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        self.controller.add_paths(
            [path for path in paths if path.suffix.lower() in AUDIO_EXTENSIONS]
        )
        event.acceptProposedAction()
