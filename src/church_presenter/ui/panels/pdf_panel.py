from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QImage, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from church_presenter.domain.enums import Availability, ChannelRole, MediaType, SortField
from church_presenter.domain.models import Content, FileItem
from church_presenter.services.file_library_service import item_from_path, scan_library, sort_items
from church_presenter.services.pdf_service import PdfRenderCoordinator, pdf_page_count
from church_presenter.ui.labels import channel_label


class _ScanSignals(QObject):
    completed = Signal(object, str, object)


class _ScanTask(QRunnable):
    def __init__(
        self,
        folder: Path,
        extras: list[Path],
        sort_field: SortField,
        descending: bool,
        token: object,
    ) -> None:
        super().__init__()
        self.folder = folder
        self.extras = extras
        self.sort_field = sort_field
        self.descending = descending
        self.token = token
        self.signals = _ScanSignals()

    def run(self) -> None:
        error_message = ""
        try:
            items = scan_library(self.folder, MediaType.PDF)
            known = {item.path.resolve() for item in items}
            for path in self.extras:
                if path.resolve() not in known:
                    items.append(item_from_path(path, MediaType.PDF))
            checked: list[FileItem] = []
            for item in items:
                if item.availability is not Availability.AVAILABLE:
                    checked.append(item)
                    continue
                try:
                    pdf_page_count(item.path)
                except Exception as error:  # background probe boundary
                    item = replace(
                        item,
                        availability=Availability.ERROR,
                        error_message=str(error),
                    )
                checked.append(item)
            result = sort_items(checked, self.sort_field, self.descending)
        except Exception as caught:  # background scan boundary
            result = []
            error_message = str(caught)
        self.signals.completed.emit(result, error_message, self.token)


class PdfPanel(QWidget):
    """Asynchronous PDF library, thumbnails, and channel preview selection."""

    preview_requested = Signal(str, object, bool)
    preview_ready = Signal(str, bool, str)
    send_to_both_requested = Signal(object, bool)
    take_requested = Signal(str)
    take_both_requested = Signal()
    link_mode_changed = Signal(bool)
    folder_changed = Signal(str)
    selection_changed = Signal(str, int)

    def __init__(
        self,
        coordinator: PdfRenderCoordinator,
        folder: Path | None = None,
        sort_field: SortField = SortField.NAME,
        descending: bool = False,
        prepare_sizes: dict[ChannelRole, QSize] | None = None,
        restore_path: Path | None = None,
        restore_page: int = 0,
        link_outputs: bool = False,
        page_orders: dict[str, list[int]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._compact_mode = False
        self.coordinator = coordinator
        self.folder = folder or Path.home()
        del sort_field, descending  # Retained in the constructor for call-site compatibility.
        # PDF order is intentionally fixed so operators see the same list every time.
        self.sort_field = SortField.NAME
        self.descending = True
        self.items: list[FileItem] = []
        self.extra_paths: list[Path] = []
        self.current_path: Path | None = None
        self.page_count = 0
        self.preview_page = 0
        self.preview_position = 0
        self.page_order: list[int] = []
        del page_orders  # Retained for settings-file and call-site compatibility.
        self.live_pages = {ChannelRole.BROADCAST: -1, ChannelRole.VENUE: -1}
        self._scan_token = ""
        self._page_token = ""
        self._page_job_token: object = ""
        self._both_token = ""
        self._both_job_tokens: set[object] = set()
        self._thumbnail_tokens: dict[object, int] = {}
        self._requested_pages: set[int] = set()
        self._both_pending: set[ChannelRole] = set()
        self.prepare_sizes = prepare_sizes or {
            ChannelRole.BROADCAST: QSize(1920, 1080),
            ChannelRole.VENUE: QSize(1920, 1080),
        }
        self._restore_path = restore_path
        self._restore_page = restore_page
        self._tasks: set[_ScanTask] = set()
        self.pool = QThreadPool.globalInstance()
        layout = QVBoxLayout(self)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(8)
        self.folder_label = QLabel(str(self.folder))
        self.folder_label.setMinimumWidth(0)
        self.folder_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.folder_label.setToolTip(str(self.folder))
        self.folder_label.setWordWrap(True)
        self.folder_label.setProperty("role", "secondary")
        folder_button = QPushButton("PDF 폴더")
        refresh_button = QPushButton("새로고침")
        library_actions = QHBoxLayout()
        library_actions.setSpacing(8)
        library_actions.addWidget(folder_button)
        library_actions.addWidget(refresh_button)
        target_actions = QHBoxLayout()
        target_actions.setSpacing(12)
        self.venue_target_check = QCheckBox("현장 Preview")
        self.broadcast_target_check = QCheckBox("송출 Preview")
        self.venue_target_check.setChecked(True)
        target_actions.addWidget(self.venue_target_check)
        target_actions.addWidget(self.broadcast_target_check)
        target_actions.addStretch()
        left_layout.addWidget(self.folder_label)
        left_layout.addLayout(library_actions)
        left_layout.addLayout(target_actions)
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.file_list.setMinimumWidth(300)
        left_layout.addWidget(self.file_list, 1)
        self.splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.status = QLabel("PDF를 선택하십시오.")
        right_layout.addWidget(self.status)
        self.thumbnail_list = QListWidget()
        self.thumbnail_list.setObjectName("PdfThumbnailList")
        self.thumbnail_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbnail_list.setIconSize(QSize(144, 90))
        self.thumbnail_list.setGridSize(QSize(166, 122))
        self.thumbnail_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbnail_list.setMovement(QListView.Movement.Static)
        self.thumbnail_list.setFlow(QListView.Flow.LeftToRight)
        self.thumbnail_list.setWrapping(True)
        self.thumbnail_list.setUniformItemSizes(True)
        self.thumbnail_list.setSpacing(4)
        self.thumbnail_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.thumbnail_list.setDragEnabled(False)
        self.thumbnail_list.setAcceptDrops(False)
        self.thumbnail_list.setDropIndicatorShown(False)
        self.thumbnail_list.verticalScrollBar().valueChanged.connect(
            lambda _value: self._schedule_visible_thumbnails()
        )
        right_layout.addWidget(self.thumbnail_list, 1)
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.setFixedWidth(68)
        self.go_button = QPushButton("페이지 이동")
        self.send_both_button = QPushButton("Send to Both")
        self.send_both_button.setProperty("variant", "primary")
        self.take_button = QPushButton("TAKE selected channel")
        self.take_both_button = QPushButton("TAKE BOTH")
        self.take_button.setProperty("variant", "take")
        self.take_both_button.setProperty("variant", "take")
        self.page_controls_widget = QWidget()
        self.page_controls_layout = QHBoxLayout(self.page_controls_widget)
        self.page_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.page_controls_layout.setSpacing(8)
        self.page_controls_layout.addWidget(self.page_spin)
        self.page_controls_layout.addWidget(self.go_button)
        self.page_controls_layout.addStretch()
        self.take_controls_widget = QWidget()
        take_controls_layout = QHBoxLayout(self.take_controls_widget)
        take_controls_layout.setContentsMargins(0, 0, 0, 0)
        take_controls_layout.setSpacing(8)
        take_controls_layout.addStretch()
        action_widgets: tuple[QWidget, ...] = (
            self.send_both_button,
            self.take_button,
            self.take_both_button,
        )
        for widget in action_widgets:
            take_controls_layout.addWidget(widget)
        self.action_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.action_layout.setSpacing(8)
        self.action_layout.addWidget(self.page_controls_widget, 1)
        self.action_layout.addWidget(self.take_controls_widget, 1)
        self.action_layout.setAlignment(
            self.page_controls_widget,
            Qt.AlignmentFlag.AlignVCenter,
        )
        self.action_layout.setAlignment(
            self.take_controls_widget,
            Qt.AlignmentFlag.AlignVCenter,
        )
        right_layout.addLayout(self.action_layout)
        self.splitter.addWidget(right)
        self.splitter.setCollapsible(0, False)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([320, 780])
        layout.addWidget(self.splitter)

        folder_button.clicked.connect(self.choose_folder)
        refresh_button.clicked.connect(self.refresh)
        self.file_list.currentRowChanged.connect(self._file_selected)
        self.thumbnail_list.currentRowChanged.connect(self._thumbnail_selected)
        self.go_button.clicked.connect(lambda: self.navigate(self.page_spin.value() - 1))
        self.send_both_button.clicked.connect(self.send_to_both)
        self.take_button.clicked.connect(lambda: self.take_requested.emit(self.target_role.value))
        self.take_both_button.clicked.connect(self.take_both_requested)
        self.venue_target_check.toggled.connect(self._target_toggled)
        self.broadcast_target_check.toggled.connect(self._target_toggled)
        coordinator.rendered.connect(self._rendered)
        self._link_mode = False
        self.set_link_outputs(link_outputs, emit=False)
        self.refresh()

    @property
    def target_role(self) -> ChannelRole:
        return self.target_roles[0]

    @property
    def target_roles(self) -> tuple[ChannelRole, ...]:
        """Return the independently selected Preview channels."""
        roles: list[ChannelRole] = []
        if self.venue_target_check.isChecked():
            roles.append(ChannelRole.VENUE)
        if self.broadcast_target_check.isChecked():
            roles.append(ChannelRole.BROADCAST)
        return tuple(roles)

    @property
    def link_outputs(self) -> bool:
        return len(self.target_roles) == 2

    def set_target_role(self, role: ChannelRole) -> None:
        self._set_target_checks((role,))
        self._apply_target_selection(emit=True)

    def set_link_outputs(self, enabled: bool, *, emit: bool = True) -> None:
        roles: tuple[ChannelRole, ...]
        if enabled:
            roles = (ChannelRole.VENUE, ChannelRole.BROADCAST)
        elif len(self.target_roles) == 1:
            roles = self.target_roles
        else:
            roles = (ChannelRole.VENUE,)
        self._set_target_checks(roles)
        self._apply_target_selection(emit=emit)

    def _set_target_checks(self, roles: tuple[ChannelRole, ...]) -> None:
        for checkbox in (self.venue_target_check, self.broadcast_target_check):
            checkbox.blockSignals(True)
        self.venue_target_check.setChecked(ChannelRole.VENUE in roles)
        self.broadcast_target_check.setChecked(ChannelRole.BROADCAST in roles)
        for checkbox in (self.venue_target_check, self.broadcast_target_check):
            checkbox.blockSignals(False)

    def _apply_target_selection(self, *, emit: bool) -> None:
        linked = self.link_outputs
        self.take_button.setEnabled(not linked)
        self.take_both_button.setEnabled(True)
        changed = linked != self._link_mode
        self._link_mode = linked
        if emit and changed:
            self.link_mode_changed.emit(linked)

    def _target_toggled(self, _checked: bool) -> None:
        if not self.target_roles:
            checkbox = self.sender()
            if isinstance(checkbox, QCheckBox):
                checkbox.blockSignals(True)
                checkbox.setChecked(True)
                checkbox.blockSignals(False)
            return
        self._apply_target_selection(emit=True)
        if self.link_outputs and self.current_path is not None:
            self.send_to_both()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Stack bottom controls only when the PDF workspace becomes narrow."""
        self.set_compact_actions(self._compact_mode or event.size().width() < 1050)
        super().resizeEvent(event)

    def set_compact_mode(self, compact: bool) -> None:
        """Reduce PDF library chrome while preserving page order and selection."""
        self._compact_mode = compact
        icon_size = QSize(120, 75) if compact else QSize(144, 90)
        grid_size = QSize(142, 106) if compact else QSize(166, 122)
        self.thumbnail_list.setIconSize(icon_size)
        self.thumbnail_list.setGridSize(grid_size)
        self.file_list.setMinimumWidth(260 if compact else 300)
        for row in range(self.thumbnail_list.count()):
            self.thumbnail_list.item(row).setSizeHint(grid_size)
        self.set_compact_actions(compact or self.width() < 1050)

    def set_compact_actions(self, compact: bool) -> None:
        """Keep one action row while shortening labels in narrow workspaces."""
        self.action_layout.setDirection(QBoxLayout.Direction.LeftToRight)
        self.send_both_button.setText("Send Both" if compact else "Send to Both")
        self.take_button.setText("TAKE" if compact else "TAKE selected channel")
        self.send_both_button.setToolTip("송출과 현장 Preview를 함께 준비")
        self.take_button.setToolTip("선택한 한 채널을 Live로 전환")
        self.action_layout.invalidate()
        panel_layout = self.layout()
        if panel_layout is not None:
            panel_layout.invalidate()
            panel_layout.activate()
        self.splitter.updateGeometry()
        self.updateGeometry()

    def choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "PDF 폴더", str(self.folder))
        if selected:
            self.folder = Path(selected)
            self.extra_paths.clear()
            self.folder_label.setText(selected)
            self.folder_label.setToolTip(selected)
            self.folder_changed.emit(selected)
            self.refresh()

    def refresh(self) -> None:
        self.status.setText("PDF 라이브러리 검색 중…")
        self._scan_token = uuid4().hex
        task = _ScanTask(
            self.folder,
            list(self.extra_paths),
            self.sort_field,
            self.descending,
            self._scan_token,
        )
        self._tasks.add(task)
        task.signals.completed.connect(self._scan_completed)
        self.pool.start(task)

    def _scan_completed(self, items: list[FileItem], error: str, token: object) -> None:
        sender = self.sender()
        self._tasks = {task for task in self._tasks if task.signals is not sender}
        if token != self._scan_token:
            return
        self.items = items
        self.file_list.clear()
        for item in items:
            modified = datetime.fromtimestamp(item.modified_time).strftime("%Y-%m-%d %H:%M")
            prefix = "⚠ " if item.availability is not Availability.AVAILABLE else ""
            row = QListWidgetItem(f"{prefix}{item.display_name}\n{modified}")
            row.setToolTip(item.error_message or str(item.path))
            self.file_list.addItem(row)
        self.status.setText(error or f"PDF {len(items)}개")
        if self._restore_path is not None:
            resolved = self._restore_path.resolve()
            for index, item in enumerate(items):
                if item.path.resolve() == resolved:
                    self.file_list.setCurrentRow(index)
                    break

    def _file_selected(self, row: int) -> None:
        if not 0 <= row < len(self.items):
            return
        item = self.items[row]
        if item.availability is not Availability.AVAILABLE:
            self.status.setText(f"PDF 오류: {item.error_message}")
            return
        self.current_path = item.path
        try:
            self.page_count = pdf_page_count(item.path)
        except Exception as error:
            self.status.setText(f"PDF 오류: {error}")
            return
        self.page_spin.setRange(1, max(1, self.page_count))
        self.thumbnail_list.clear()
        self.coordinator.cancel(self._page_job_token)
        for token in self._both_job_tokens:
            self.coordinator.cancel(token)
        self._both_job_tokens.clear()
        for token in tuple(self._thumbnail_tokens):
            self.coordinator.cancel(token)
        self._thumbnail_tokens.clear()
        self._requested_pages.clear()
        self.page_order = list(range(self.page_count))
        for page in self.page_order:
            thumbnail = QListWidgetItem(f"{page + 1}")
            thumbnail.setData(Qt.ItemDataRole.UserRole, page)
            thumbnail.setSizeHint(self.thumbnail_list.gridSize())
            thumbnail.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.thumbnail_list.addItem(thumbnail)
        self.status.setText(f"{item.display_name} · {self.page_count} pages · 썸네일 준비 중…")
        initial_page = (
            self._restore_page
            if self._restore_path is not None
            and item.path.resolve() == self._restore_path.resolve()
            else 0
        )
        self._restore_path = None
        self.navigate(initial_page)
        self._schedule_visible_thumbnails()

    def _thumbnail_selected(self, page: int) -> None:
        item = self.thumbnail_list.item(page)
        if item is not None:
            self.navigate(int(item.data(Qt.ItemDataRole.UserRole)))

    def navigate(self, page: int) -> None:
        self.navigate_for_roles(page, self.target_roles)

    def navigate_for_roles(
        self,
        page: int,
        roles: tuple[ChannelRole, ...],
    ) -> None:
        """Select a page and prepare it for the requested Preview channels."""
        if self.current_path is None or self.page_count < 1:
            return
        requested_roles = tuple(dict.fromkeys(roles))
        if not requested_roles:
            return
        self.preview_page = max(0, min(page, self.page_count - 1))
        self.preview_position = self.page_order.index(self.preview_page)
        self._request_thumbnail(self.preview_page, priority=2)
        self.page_spin.setValue(self.preview_page + 1)
        if self.thumbnail_list.currentRow() != self.preview_position:
            self.thumbnail_list.blockSignals(True)
            self.thumbnail_list.setCurrentRow(self.preview_position)
            self.thumbnail_list.blockSignals(False)
        content = Content.pdf(self.current_path, self.preview_page)
        if len(requested_roles) == 2:
            self._prepare_both(content)
            self.selection_changed.emit(str(self.current_path), self.preview_page)
            return
        role = requested_roles[0]
        for token in self._both_job_tokens:
            self.coordinator.cancel(token)
        self._both_job_tokens.clear()
        self._both_pending.clear()
        self._both_token = ""
        self.preview_requested.emit(role.value, content, False)
        self.status.setText("고해상도 Preview 준비 중… 기존 Live 유지")
        self._page_token = uuid4().hex
        token = ("preview", self._page_token, role)
        self.coordinator.cancel(self._page_job_token)
        self._page_job_token = token
        self.coordinator.request(
            self.current_path,
            self.preview_page,
            self.prepare_sizes[role],
            token,
            priority=3,
        )
        self.selection_changed.emit(str(self.current_path), self.preview_page)

    def set_preview_position(self, page: int) -> None:
        """Synchronize page controls without starting another render request."""
        if not 0 <= page < self.page_count or page not in self.page_order:
            return
        self.preview_page = page
        self.preview_position = self.page_order.index(page)
        self.page_spin.setValue(page + 1)
        self.thumbnail_list.blockSignals(True)
        self.thumbnail_list.setCurrentRow(self.preview_position)
        self.thumbnail_list.blockSignals(False)
        self._request_thumbnail(page, priority=2)

    def move_preview(self, offset: int) -> None:
        if not self.page_order:
            return
        target = max(0, min(self.preview_position + offset, len(self.page_order) - 1))
        self.navigate(self.page_order[target])

    def move_preview_for_roles(
        self,
        offset: int,
        roles: tuple[ChannelRole, ...],
    ) -> None:
        """Move in presentation order and update only the given channels."""
        if not self.page_order:
            return
        target = max(0, min(self.preview_position + offset, len(self.page_order) - 1))
        self.navigate_for_roles(self.page_order[target], roles)

    def navigate_first(self) -> None:
        if self.page_order:
            self.navigate(self.page_order[0])

    def navigate_first_for_roles(self, roles: tuple[ChannelRole, ...]) -> None:
        if self.page_order:
            self.navigate_for_roles(self.page_order[0], roles)

    def navigate_last(self) -> None:
        if self.page_order:
            self.navigate(self.page_order[-1])

    def navigate_last_for_roles(self, roles: tuple[ChannelRole, ...]) -> None:
        if self.page_order:
            self.navigate_for_roles(self.page_order[-1], roles)

    def send_to_both(self) -> None:
        if self.current_path is None:
            return
        content = Content.pdf(self.current_path, self.preview_page)
        self._prepare_both(content)

    def _prepare_both(self, content: Content) -> None:
        if self.current_path is None:
            return
        self.coordinator.cancel(self._page_job_token)
        self._page_job_token = ""
        self._page_token = ""
        self.send_to_both_requested.emit(content, False)
        self.status.setText("두 출력 해상도의 Preview 준비 중…")
        for token in self._both_job_tokens:
            self.coordinator.cancel(token)
        self._both_job_tokens.clear()
        self._both_token = uuid4().hex
        self._both_pending = {ChannelRole.BROADCAST, ChannelRole.VENUE}
        for role in tuple(self._both_pending):
            token = ("both", self._both_token, role)
            self._both_job_tokens.add(token)
            self.coordinator.request(
                self.current_path,
                self.preview_page,
                self.prepare_sizes[role],
                token,
                priority=3,
            )

    def set_prepare_sizes(self, prepare_sizes: dict[ChannelRole, QSize]) -> None:
        """Update high-resolution readiness targets after screen configuration changes."""
        self.prepare_sizes = dict(prepare_sizes)

    def _schedule_visible_thumbnails(self) -> None:
        QTimer.singleShot(0, self._request_visible_thumbnails)

    def _request_visible_thumbnails(self) -> None:
        viewport = self.thumbnail_list.viewport().rect()
        requested = False
        for page in range(self.thumbnail_list.count()):
            item = self.thumbnail_list.item(page)
            if self.thumbnail_list.visualItemRect(item).intersects(viewport):
                actual_page = int(item.data(Qt.ItemDataRole.UserRole))
                self._request_thumbnail(actual_page, priority=1)
                requested = True
        if not requested and self.page_count:
            self._request_thumbnail(self.preview_page, priority=2)

    def _request_thumbnail(self, page: int, *, priority: int) -> None:
        if self.current_path is None or page in self._requested_pages:
            return
        self._requested_pages.add(page)
        token = ("thumbnail", uuid4().hex)
        self._thumbnail_tokens[token] = page
        self.coordinator.request(
            self.current_path,
            page,
            QSize(320, 200),
            token,
            priority=priority,
        )

    def _item_for_page(self, page: int) -> QListWidgetItem | None:
        for row in range(self.thumbnail_list.count()):
            item = self.thumbnail_list.item(row)
            if int(item.data(Qt.ItemDataRole.UserRole)) == page:
                return item
        return None

    def mark_live(self, role: ChannelRole, page: int | None = None) -> None:
        self.live_pages[role] = self.preview_page if page is None else page

    def mark_both_live(self) -> None:
        self.live_pages[ChannelRole.BROADCAST] = self.preview_page
        self.live_pages[ChannelRole.VENUE] = self.preview_page
        self.mark_live(ChannelRole.BROADCAST)

    def _rendered(self, _key: object, image: QImage, error: str, token: object) -> None:
        if token in self._thumbnail_tokens:
            page = self._thumbnail_tokens.pop(token)
            item = self._item_for_page(page)
            if item is not None:
                if error:
                    item.setText(f"{page + 1}\n⚠ {error}")
                else:
                    item.setIcon(QIcon(QPixmap.fromImage(image)))
            return
        if not (isinstance(token, tuple) and len(token) == 3 and token[0] == "preview"):
            if not (isinstance(token, tuple) and len(token) == 3 and token[0] == "both"):
                return
            _, request_token, role = token
            if request_token != self._both_token:
                return
            self._both_job_tokens.discard(token)
            if error:
                self.status.setText(f"{channel_label(role)} 준비 실패: {error}")
                self.preview_ready.emit(role.value, False, error)
                self._both_pending.clear()
                return
            self._both_pending.discard(role)
            self.preview_ready.emit(role.value, True, "")
            if not self._both_pending:
                self.status.setText("두 Preview 준비 완료 · TAKE BOTH 가능")
            return
        _, request_token, role = token
        if request_token != self._page_token:
            return
        self._page_job_token = ""
        if error:
            self.status.setText(f"PDF 렌더링 실패: {error}")
            self.preview_ready.emit(role.value, False, error)
            return
        self.status.setText("준비 완료 · TAKE 가능")
        self.preview_ready.emit(role.value, True, "")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if any(Path(url.toLocalFile()).suffix.lower() == ".pdf" for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if Path(url.toLocalFile()).suffix.lower() == ".pdf"
        ]
        if paths:
            self.extra_paths.extend(path for path in paths if path not in self.extra_paths)
            event.acceptProposedAction()
            self.refresh()
