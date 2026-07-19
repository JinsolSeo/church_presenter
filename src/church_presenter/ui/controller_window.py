from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QEventLoop, QObject, QSize, Qt
from PySide6.QtGui import QCloseEvent, QImage, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from church_presenter.domain.enums import ChannelRole, ContentType, PauseReason, PlaybackStatus
from church_presenter.domain.models import AppSettings, Content, SubtitleDocument
from church_presenter.domain.state import ApplicationState
from church_presenter.media.audio_controller import AudioPlaybackController
from church_presenter.media.base import MediaPlaybackBackend
from church_presenter.media.playlist import PlaylistService
from church_presenter.media.qt_media_backend import QtMediaBackend
from church_presenter.media.video_manager import VideoPlaybackManager
from church_presenter.rendering.output_surface import AspectRatioContainer, OutputSurface
from church_presenter.services.audio_device_service import AudioDeviceService
from church_presenter.services.pdf_service import PdfRenderCoordinator
from church_presenter.services.screen_service import ScreenService, validate_role_assignment
from church_presenter.services.settings_service import SettingsService
from church_presenter.ui.dialogs.screen_settings_dialog import ScreenSettingsDialog
from church_presenter.ui.dialogs.subtitle_style_dialog import SubtitleStyleDialog
from church_presenter.ui.output_window import BroadcastOutputWindow, VenueOutputWindow
from church_presenter.ui.panels.audio_panel import AudioPanel
from church_presenter.ui.panels.black_panel import BlackPanel
from church_presenter.ui.panels.pdf_panel import PdfPanel
from church_presenter.ui.panels.subtitle_panel import SubtitlePanel
from church_presenter.ui.panels.video_panel import VideoPanel
from church_presenter.ui.simulation_window import SimulationWindow

LOGGER = logging.getLogger(__name__)


class ChannelMonitor(QFrame):
    """Labelled 16:9 Controller mirror for Preview or Live."""

    def __init__(
        self,
        title: str,
        coordinator: PdfRenderCoordinator,
        live: bool,
    ) -> None:
        super().__init__()
        self.setObjectName("LiveMonitor" if live else "PreviewMonitor")
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.title = QLabel(title)
        self.title.setStyleSheet("font-weight:800;")
        self.mode = QLabel("BLACK")
        self.mode.setStyleSheet(
            "font-weight:800;color:#dc2626;" if live else "font-weight:800;color:#2563eb;"
        )
        header.addWidget(self.title)
        header.addStretch()
        header.addWidget(self.mode)
        layout.addLayout(header)
        self.surface = OutputSurface(coordinator)
        layout.addWidget(AspectRatioContainer(self.surface), 1)

    def set_content(self, content: Content, fade_duration_ms: int = 0) -> None:
        self.mode.setText(content.kind.value.upper())
        if content != self.surface.target_content:
            self.surface.set_content(content, fade_duration_ms)


class ControllerWindow(QMainWindow):
    """Operator GUI coordinating all Phase 1 state and outputs."""

    def __init__(
        self,
        application: QApplication,
        screen_service: ScreenService,
        settings_service: SettingsService,
        settings: AppSettings,
        settings_warning: str = "",
        previous_unclean_exit: bool = False,
        video_backend_factory: Callable[[], MediaPlaybackBackend] | None = None,
        audio_backend: MediaPlaybackBackend | None = None,
    ) -> None:
        super().__init__()
        self.application = application
        self.screen_service = screen_service
        self.settings_service = settings_service
        self.settings = settings
        self.state = ApplicationState()
        self.coordinator = PdfRenderCoordinator()
        self.audio_device_service = AudioDeviceService()
        video_factory = video_backend_factory or (
            lambda: QtMediaBackend(
                video=True,
                audio_device_resolver=self.audio_device_service.resolve,
            )
        )
        self.video_manager = VideoPlaybackManager(
            video_factory,
            volume=settings.video_volume / 100,
            muted=settings.video_muted,
        )
        self.playlist_service = PlaylistService()
        playlist = None
        if settings.last_playlist:
            try:
                playlist_path = Path(settings.last_playlist)
                if playlist_path.is_file():
                    playlist = self.playlist_service.load(playlist_path)
            except (OSError, ValueError, TypeError):
                LOGGER.exception("Could not restore background-music playlist")
        if playlist is not None:
            playlist.repeat_mode = settings.repeat_mode
        self.audio_controller = AudioPlaybackController(
            audio_backend
            or QtMediaBackend(
                video=False,
                audio_device_resolver=self.audio_device_service.resolve,
            ),
            playlist,
            volume=settings.music_volume / 100,
            muted=settings.music_muted,
        )
        self._audio_startup_warning = ""
        if not self._apply_audio_output_device(settings.audio_output_device_id):
            settings.audio_output_device_id = ""
            self._apply_audio_output_device("")
            self._audio_startup_warning = (
                "저장된 오디오 출력 장치를 찾을 수 없어 시스템 기본 출력으로 전환했습니다."
            )
        if playlist is not None:
            self.audio_controller.cue_current(settings.audio_position_ms)
        self.broadcast_output: BroadcastOutputWindow | None = None
        self.venue_output: VenueOutputWindow | None = None
        self.broadcast_simulator: SimulationWindow | None = None
        self.venue_simulator: SimulationWindow | None = None
        self._closing = False
        self.setWindowTitle("Church Presenter")
        self.resize(1280, 920)
        if settings.controller_geometry:
            try:
                self.restoreGeometry(
                    QByteArray.fromBase64(settings.controller_geometry.encode("ascii"))
                )
            except (ValueError, UnicodeError):
                LOGGER.exception("Could not restore Controller geometry")
        self._build_ui()
        self._connect_signals()
        self.audio_device_service.outputs_changed.connect(self._audio_outputs_changed)
        self.application.installEventFilter(self)
        self.application.focusChanged.connect(self._focus_changed)
        self._restore_content()
        self._restore_panel_layout()
        self._move_controller_to_assigned_screen()
        self._refresh_all()
        if len(screen_service.screens()) < 3:
            self.screen_status.setText(
                f"화면 {len(screen_service.screens())}개 감지 · Simulation Mode 권장"
            )
        if self._audio_startup_warning:
            self.status.setText(self._audio_startup_warning)
        if settings_warning:
            self.status.setText(settings_warning)
        if previous_unclean_exit:
            self.status.setText(
                "이전 실행이 정상 종료되지 않았습니다. 출력 상태는 안전하게 BLACK입니다."
            )

    def _build_ui(self) -> None:
        root_scroll = QScrollArea()
        root_scroll.setWidgetResizable(True)
        root = QWidget()
        root_scroll.setWidget(root)
        self.setCentralWidget(root_scroll)
        layout = QVBoxLayout(root)
        top = QHBoxLayout()
        title = QLabel("Church Presenter · Phase 2")
        title.setStyleSheet("font-size:22px;font-weight:800;")
        self.screen_status = QLabel("화면 상태 확인 중")
        self.status = QLabel("준비됨 · 모든 Live는 BLACK")
        self.status.setWordWrap(True)
        settings_button = QPushButton("화면 / 오디오 설정")
        self.start_outputs_button = QPushButton("출력 시작")
        self.stop_outputs_button = QPushButton("출력 중지")
        self.start_outputs_button.setStyleSheet("font-weight:800;background:#2563eb;color:white;")
        for widget in (
            title,
            self.screen_status,
            settings_button,
            self.start_outputs_button,
            self.stop_outputs_button,
        ):
            top.addWidget(widget)
        top.addStretch()
        layout.addLayout(top)
        layout.addWidget(self.status)

        grid = QGridLayout()
        self.broadcast_preview = ChannelMonitor("Broadcast Preview", self.coordinator, False)
        self.broadcast_live = ChannelMonitor("Broadcast Live", self.coordinator, True)
        self.venue_preview = ChannelMonitor("Venue Preview", self.coordinator, False)
        self.venue_live = ChannelMonitor("Venue Live", self.coordinator, True)
        self.take_broadcast = QPushButton("TAKE → BROADCAST")
        self.take_venue = QPushButton("TAKE → VENUE")
        take_style = "font-weight:800;background:#f59e0b;color:#111827;padding:9px;"
        self.take_broadcast.setStyleSheet(take_style)
        self.take_venue.setStyleSheet(take_style)
        grid.addWidget(self.broadcast_preview, 0, 0)
        grid.addWidget(self.broadcast_live, 0, 1)
        grid.addWidget(self.take_broadcast, 1, 0, 1, 2)
        grid.addWidget(self.venue_preview, 2, 0)
        grid.addWidget(self.venue_live, 2, 1)
        grid.addWidget(self.take_venue, 3, 0, 1, 2)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(2, 1)
        layout.addLayout(grid, 2)

        self.sync_bar = QFrame()
        self.sync_bar.setObjectName("SyncControl")
        self.sync_bar.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.sync_bar.setToolTip(
            "이 영역에 포커스가 있으면 Left/Right로 Preview를 함께 이동하고 "
            "Enter로 TAKE BOTH를 실행합니다."
        )
        sync_layout = QHBoxLayout(self.sync_bar)
        self.sync_content_check = QCheckBox("자막 + PDF 동시 진행")
        self.sync_content_check.setObjectName("SyncContentCheck")
        self.sync_content_check.setChecked(self.settings.subtitle_pdf_linked)
        sync_description = QLabel("Broadcast 자막 · Venue PDF · 방향키 동시 이동")
        self.sync_previous_button = QPushButton("◀ 함께 이전")
        self.sync_next_button = QPushButton("함께 다음 ▶")
        self.sync_take_button = QPushButton("TAKE BOTH · 자막 + PDF")
        self.sync_take_button.setObjectName("DangerButton")
        sync_widgets: tuple[QWidget, ...] = (
            self.sync_content_check,
            sync_description,
            self.sync_previous_button,
            self.sync_next_button,
            self.sync_take_button,
        )
        for sync_widget in sync_widgets:
            sync_layout.addWidget(sync_widget)
        sync_layout.addStretch()
        layout.addWidget(self.sync_bar)

        presets, default_preset, warning = self.settings_service.load_presets()
        preset_name = (
            self.settings.current_style_preset
            if self.settings.current_style_preset in presets
            else default_preset
        )
        self.subtitle_style = presets[preset_name]
        if warning:
            self.status.setText(warning)
        self.tabs = QTabWidget()
        self.subtitle_panel = SubtitlePanel(
            self.subtitle_style,
            self.settings.key_color,
            self.settings.subtitle_group_size,
        )
        pdf_folder = Path(self.settings.pdf_folder) if self.settings.pdf_folder else None
        self.pdf_panel = PdfPanel(
            self.coordinator,
            pdf_folder,
            self.settings.sort_field,
            self.settings.sort_descending,
            self._pdf_prepare_sizes(),
            Path(self.settings.last_pdf_file) if self.settings.last_pdf_file else None,
            self.settings.last_pdf_page,
            link_outputs=(self.settings.pdf_link_outputs and not self.settings.subtitle_pdf_linked),
            page_orders=self.settings.pdf_page_orders,
        )
        self.black_panel = BlackPanel()
        self.video_panel = VideoPanel(
            self.video_manager,
            Path(self.settings.video_folder) if self.settings.video_folder else None,
            self.settings.video_sort_field,
            self.settings.video_sort_descending,
            self.settings.video_volume,
            self.settings.video_muted,
            self.settings.fade_duration_ms,
            Path(self.settings.last_video_file) if self.settings.last_video_file else None,
        )
        self.audio_panel = AudioPanel(
            self.audio_controller,
            self.playlist_service,
            Path(self.settings.audio_folder) if self.settings.audio_folder else None,
            self.settings.audio_sort_field,
            self.settings.audio_sort_descending,
        )
        if self.settings.last_playlist:
            self.audio_panel.playlist_path = Path(self.settings.last_playlist)
        self.tabs.addTab(self.subtitle_panel, "자막")
        self.tabs.addTab(self.pdf_panel, "PDF")
        self.tabs.addTab(self.video_panel, "영상")
        self.tabs.addTab(self.audio_panel, "배경음악")
        self.tabs.addTab(self.black_panel, "검은 화면")
        layout.addWidget(self.tabs, 3)

        settings_button.clicked.connect(self.open_screen_settings)
        self.start_outputs_button.clicked.connect(self.start_outputs)
        self.stop_outputs_button.clicked.connect(self.stop_outputs)

    def _connect_signals(self) -> None:
        self.take_broadcast.clicked.connect(lambda: self.take(ChannelRole.BROADCAST))
        self.take_venue.clicked.connect(lambda: self.take(ChannelRole.VENUE))
        self.subtitle_panel.preview_requested.connect(
            lambda content: self.set_preview(ChannelRole.BROADCAST, content, True)
        )
        self.subtitle_panel.take_requested.connect(lambda: self.take(ChannelRole.BROADCAST))
        self.subtitle_panel.style_requested.connect(self.open_style_settings)
        self.subtitle_panel.document_changed.connect(self._subtitle_document_changed)
        self.pdf_panel.preview_requested.connect(self.set_preview)
        self.pdf_panel.preview_ready.connect(self.mark_preview_ready)
        self.pdf_panel.send_to_both_requested.connect(self.send_to_both)
        self.pdf_panel.take_requested.connect(self.take)
        self.pdf_panel.take_both_requested.connect(self.take_both)
        self.pdf_panel.link_mode_changed.connect(self._pdf_link_mode_changed)
        self.pdf_panel.page_order_changed.connect(self._pdf_page_order_changed)
        self.pdf_panel.folder_changed.connect(self._pdf_folder_changed)
        self.pdf_panel.selection_changed.connect(self._pdf_selection_changed)
        self.black_panel.preview_requested.connect(
            lambda role, content: self.set_preview(role, content, True)
        )
        self.black_panel.send_to_both_requested.connect(
            lambda content: self.send_to_both(content, True)
        )
        self.black_panel.take_requested.connect(self.take)
        self.black_panel.take_both_requested.connect(self.take_both)
        self.video_panel.preview_requested.connect(self.set_preview)
        self.video_panel.send_to_both_requested.connect(self.send_to_both)
        self.video_panel.take_requested.connect(self._take_video)
        self.video_panel.take_both_requested.connect(self._take_both_videos)
        self.video_panel.folder_changed.connect(self._video_folder_changed)
        self.video_panel.selection_changed.connect(self._video_selection_changed)
        self.video_panel.settings_changed.connect(self._media_settings_changed)
        self.audio_panel.folder_changed.connect(self._audio_folder_changed)
        self.audio_panel.playlist_path_changed.connect(self._playlist_path_changed)
        self.audio_panel.settings_changed.connect(self._media_settings_changed)
        self.video_manager.preview_result.connect(self._video_preview_result)
        self.video_manager.live_frame_ready.connect(self._video_live_frame)
        self.video_manager.play_started.connect(self._video_play_started)
        self.video_manager.live_ended.connect(
            lambda role: self._black_live(role, "영상 재생이 끝나 BLACK으로 전환했습니다.")
        )
        self.video_manager.live_stopped.connect(
            lambda role: self._black_live(role, "영상을 정지하고 BLACK으로 전환했습니다.")
        )
        self.video_manager.live_error.connect(
            lambda role, error: self._black_live(
                role,
                f"영상 오류로 BLACK 전환: {error}",
            )
        )
        self.screen_service.screens_changed.connect(self._screens_changed)
        self.sync_content_check.toggled.connect(self._linked_navigation_toggled)
        self.sync_previous_button.clicked.connect(lambda: self.move_linked_previews(-1))
        self.sync_next_button.clicked.connect(lambda: self.move_linked_previews(1))
        self.sync_take_button.clicked.connect(self.take_linked_previews)
        self._linked_navigation_toggled(self.sync_content_check.isChecked())

    def _restore_content(self) -> None:
        last_subtitle = (
            Path(self.settings.last_subtitle_file) if self.settings.last_subtitle_file else None
        )
        if last_subtitle and last_subtitle.is_file():
            self.subtitle_panel.load_path(last_subtitle, warn=False)

    def _restore_panel_layout(self) -> None:
        try:
            prefix, index_text = self.settings.panel_layout.split(":", maxsplit=1)
            index = int(index_text)
        except (ValueError, AttributeError):
            return
        if prefix == "tabs" and 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)

    @staticmethod
    def _normalize_role(role: ChannelRole | str) -> ChannelRole:
        return role if isinstance(role, ChannelRole) else ChannelRole(role)

    def set_preview(
        self,
        role: ChannelRole | str,
        content: Content,
        ready: bool = True,
    ) -> None:
        role = self._normalize_role(role)
        self.state.set_preview(role, content, ready=ready)
        if content.kind is not ContentType.VIDEO:
            self.video_panel.invalidate_preview(role)
        if not ready:
            self.status.setText(f"{role.value.title()} Preview 준비 중 · 기존 Live 유지")
        self._refresh_channel(role)

    def mark_preview_ready(
        self,
        role: ChannelRole | str,
        ready: bool,
        error: str,
    ) -> None:
        role = self._normalize_role(role)
        self.state.mark_preview_ready(role, ready, error)
        self.status.setText(
            f"{role.value.title()} Preview 준비 완료"
            if ready
            else f"{role.value.title()} Preview 오류: {error}"
        )
        self._refresh_channel(role)

    def send_to_both(self, content: Content, ready: bool) -> None:
        if content.kind is ContentType.SUBTITLE_KEY:
            self.status.setText("자막은 Broadcast 전용입니다.")
            return
        if content.kind is not ContentType.VIDEO:
            self.video_panel.invalidate_preview(ChannelRole.BROADCAST)
            self.video_panel.invalidate_preview(ChannelRole.VENUE)
        self.state.set_preview(ChannelRole.BROADCAST, content, ready=ready)
        self.state.set_preview(ChannelRole.VENUE, content, ready=ready)
        self._refresh_all()
        self.status.setText("동일 콘텐츠를 두 Preview에 준비했습니다. 확인 후 TAKE BOTH 하십시오.")

    def _take_video(self, role: ChannelRole | str) -> bool:
        role = self._normalize_role(role)
        if self.state.channel(role).preview_content.kind is not ContentType.VIDEO:
            self.video_panel.invalidate_preview(role)
            self.status.setText("TAKE 실패 · 현재 Preview는 영상이 아닙니다.")
            return False
        return self.take(role)

    def _take_both_videos(self) -> bool:
        roles = (ChannelRole.BROADCAST, ChannelRole.VENUE)
        if any(
            self.state.channel(role).preview_content.kind is not ContentType.VIDEO
            for role in roles
        ):
            for role in roles:
                if self.state.channel(role).preview_content.kind is not ContentType.VIDEO:
                    self.video_panel.invalidate_preview(role)
            self.status.setText("TAKE BOTH 실패 · 양쪽 Preview가 모두 영상이어야 합니다.")
            return False
        return self.take_both()

    def take(self, role: ChannelRole | str) -> bool:
        role = self._normalize_role(role)
        next_content = self.state.channel(role).preview_content
        previous_live = self.state.channel(role).live_content
        if next_content.kind is ContentType.VIDEO and (
            next_content.video_path is None
            or not self.video_manager.can_activate(role, next_content.video_path)
        ):
            self.status.setText("TAKE 실패 · 영상 첫 프레임이 아직 준비되지 않았습니다.")
            return False
        preview_valid = self.state.channel(role).validate_preview()[0]
        if preview_valid and not self._ensure_live_outputs((role,)):
            return False
        succeeded, error = self.state.take(role)
        if not succeeded:
            self.status.setText(f"TAKE 실패 · 기존 Live 유지: {error}")
            self._refresh_channel(role)
            return False
        if next_content.kind is ContentType.VIDEO:
            assert next_content.video_path is not None
            if not self.video_manager.activate_preview(role, next_content.video_path):
                self.state.channel(role).live_content = previous_live
                self.status.setText("TAKE 실패 · 기존 Live 유지: 영상 Cue 활성화 실패")
                self._refresh_channel(role)
                return False
        elif previous_live.kind is ContentType.VIDEO:
            self.video_manager.clear_live(role)
        if (
            role is ChannelRole.BROADCAST
            and self.state.broadcast.live_content.kind is ContentType.SUBTITLE_KEY
        ):
            self.subtitle_panel.mark_live()
        if self.state.channel(role).live_content.kind is ContentType.PDF_PAGE:
            self.pdf_panel.mark_live(role)
        self._push_live(role)
        self._refresh_channel(role)
        self.status.setText(f"{role.value.title()} TAKE 완료")
        return True

    def take_both(self) -> bool:
        previous = {
            ChannelRole.BROADCAST: self.state.broadcast.live_content,
            ChannelRole.VENUE: self.state.venue.live_content,
        }
        for role in (ChannelRole.BROADCAST, ChannelRole.VENUE):
            content = self.state.channel(role).preview_content
            if content.kind is ContentType.VIDEO and (
                content.video_path is None
                or not self.video_manager.can_activate(role, content.video_path)
            ):
                self.status.setText(
                    "TAKE BOTH 실패 · 양쪽 기존 Live 유지: 영상 Cue가 준비되지 않았습니다."
                )
                return False
        previews_valid = all(
            self.state.channel(role).validate_preview()[0]
            for role in (ChannelRole.BROADCAST, ChannelRole.VENUE)
        )
        if previews_valid and not self._ensure_live_outputs(
            (ChannelRole.BROADCAST, ChannelRole.VENUE)
        ):
            return False
        succeeded, error = self.state.take_both()
        if not succeeded:
            self.status.setText(f"TAKE BOTH 실패 · 양쪽 기존 Live 유지: {error}")
            self._refresh_all()
            return False
        for role in (ChannelRole.BROADCAST, ChannelRole.VENUE):
            content = self.state.channel(role).live_content
            if content.kind is ContentType.VIDEO:
                assert content.video_path is not None
                if not self.video_manager.activate_preview(role, content.video_path):
                    self.state.broadcast.live_content = previous[ChannelRole.BROADCAST]
                    self.state.venue.live_content = previous[ChannelRole.VENUE]
                    self.status.setText("TAKE BOTH 실패 · 양쪽 기존 Live 유지: 영상 활성화 실패")
                    self._refresh_all()
                    return False
            elif previous[role].kind is ContentType.VIDEO:
                self.video_manager.clear_live(role)
        video_transport_linked = self.video_manager.link_live_pair()
        self._push_live(ChannelRole.BROADCAST)
        self._push_live(ChannelRole.VENUE)
        if self.state.broadcast.live_content.kind is ContentType.SUBTITLE_KEY:
            self.subtitle_panel.mark_live()
        if self.state.broadcast.live_content.kind is ContentType.PDF_PAGE:
            self.pdf_panel.mark_live(ChannelRole.BROADCAST)
        if self.state.venue.live_content.kind is ContentType.PDF_PAGE:
            self.pdf_panel.mark_live(ChannelRole.VENUE)
        self._refresh_all()
        self.status.setText(
            "TAKE BOTH 완료 · 영상 Play/Pause/Stop 양쪽 연동"
            if video_transport_linked
            else "TAKE BOTH 원자적 전환 완료"
        )
        return True

    def _linked_navigation_toggled(self, enabled: bool) -> None:
        self.settings.subtitle_pdf_linked = enabled
        self.sync_content_check.setText(
            "☑ 자막 + PDF 동시 진행 · 켜짐" if enabled else "☐ 자막 + PDF 동시 진행 · 꺼짐"
        )
        if enabled:
            self.settings.pdf_link_outputs = False
            if self.pdf_panel.link_outputs:
                self.pdf_panel.set_link_outputs(False)
            self.status.setText(
                "동시 진행 영역에 포커스를 두면 방향키로 각 Preview 콘텐츠를 함께 준비합니다."
            )

    def _pdf_link_mode_changed(self, enabled: bool) -> None:
        self.settings.pdf_link_outputs = enabled
        if enabled and self.sync_content_check.isChecked():
            self.sync_content_check.blockSignals(True)
            self.sync_content_check.setChecked(False)
            self.sync_content_check.blockSignals(False)
            self._linked_navigation_toggled(False)
            self.status.setText(
                "PDF 양쪽 연동을 시작했습니다. 자막+PDF 동시 진행은 해제되었습니다."
            )

    def move_linked_previews(self, offset: int) -> None:
        if not self.sync_content_check.isChecked():
            self.sync_content_check.setChecked(True)
        subtitle_active, pdf_roles = self._linked_preview_targets()
        if subtitle_active:
            self.subtitle_panel.move_preview(offset)
        if pdf_roles:
            self.pdf_panel.move_preview_for_roles(offset, pdf_roles)
        if not subtitle_active and not pdf_roles:
            self.status.setText("함께 이동할 자막 또는 PDF가 Broadcast/Venue Preview에 없습니다.")
            return
        self._show_linked_position()

    def first_linked_previews(self) -> None:
        if not self.sync_content_check.isChecked():
            self.sync_content_check.setChecked(True)
        subtitle_active, pdf_roles = self._linked_preview_targets()
        if subtitle_active:
            self.subtitle_panel.navigate(0)
        if pdf_roles:
            self.pdf_panel.navigate_first_for_roles(pdf_roles)
        self._show_linked_position()

    def last_linked_previews(self) -> None:
        if not self.sync_content_check.isChecked():
            self.sync_content_check.setChecked(True)
        subtitle_active, pdf_roles = self._linked_preview_targets()
        if subtitle_active:
            self.subtitle_panel.navigate(len(self.subtitle_panel.document.cards) - 1)
        if pdf_roles:
            self.pdf_panel.navigate_last_for_roles(pdf_roles)
        self._show_linked_position()

    def take_linked_previews(self) -> bool:
        if not self.sync_content_check.isChecked():
            self.sync_content_check.setChecked(True)
        return self.take_both()

    def _linked_preview_targets(self) -> tuple[bool, tuple[ChannelRole, ...]]:
        subtitle_active = self.state.broadcast.preview_content.kind is ContentType.SUBTITLE_KEY
        pdf_roles = tuple(
            role
            for role in (ChannelRole.BROADCAST, ChannelRole.VENUE)
            if self.state.channel(role).preview_content.kind is ContentType.PDF_PAGE
        )
        return subtitle_active, pdf_roles

    def _show_linked_position(self) -> None:
        subtitle_count = len(self.subtitle_panel.document.cards)
        subtitle_position = str(self.subtitle_panel.preview_index + 1) if subtitle_count else "없음"
        pdf_position = (
            str(self.pdf_panel.preview_position + 1) if self.pdf_panel.page_order else "없음"
        )
        self.status.setText(
            f"함께 이동 · 자막 {subtitle_position}/{subtitle_count or '-'} · "
            f"PDF 순서 {pdf_position}/{len(self.pdf_panel.page_order) or '-'}"
        )

    def open_style_settings(self) -> None:
        dialog = SubtitleStyleDialog(
            self.settings_service,
            self.coordinator,
            self.subtitle_panel.subtitle_style,
            self.subtitle_panel.key_color,
            self.settings.current_style_preset,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.subtitle_style = dialog.result_style
        self.settings.key_color = dialog.result_key_color
        self.settings.current_style_preset = dialog.result_preset
        self.subtitle_panel.set_style(dialog.result_style, dialog.result_key_color)
        self.status.setText(
            "자막 스타일을 Broadcast Preview에 적용했습니다. Live는 변경되지 않았습니다."
        )

    def open_screen_settings(self) -> None:
        outputs_active = any(
            window is not None
            for window in (
                self.broadcast_output,
                self.venue_output,
                self.broadcast_simulator,
                self.venue_simulator,
            )
        )
        dialog = ScreenSettingsDialog(
            self.screen_service.screens(),
            self.settings,
            self.audio_device_service.outputs(),
            self.audio_device_service.default_description(),
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.pdf_panel.set_prepare_sizes(self._pdf_prepare_sizes())
            self._move_controller_to_assigned_screen()
            if outputs_active:
                self.start_outputs()
            else:
                self.status.setText("화면 설정 저장됨 · 출력 시작 버튼으로 적용하십시오.")
            if not self._apply_audio_output_device(self.settings.audio_output_device_id):
                self.settings.audio_output_device_id = ""
                self._apply_audio_output_device("")
                self.status.setText(
                    "선택한 오디오 장치를 사용할 수 없어 시스템 기본 출력으로 전환했습니다."
                )
            else:
                name = self._selected_audio_output_name()
                self.status.setText(f"오디오 출력 적용됨 · {name}")
            self._update_screen_status()

    def _apply_audio_output_device(self, device_id: str) -> bool:
        video_applied = self.video_manager.set_audio_output_device(device_id)
        music_applied = self.audio_controller.set_audio_output_device(device_id)
        return video_applied and music_applied

    def _selected_audio_output_name(self) -> str:
        selected = self.settings.audio_output_device_id
        if not selected:
            default = self.audio_device_service.default_description()
            return f"시스템 기본 출력 ({default})" if default else "시스템 기본 출력"
        return next(
            (
                output.description
                for output in self.audio_device_service.outputs()
                if output.id == selected
            ),
            "선택한 오디오 장치",
        )

    def _audio_outputs_changed(self) -> None:
        selected = self.settings.audio_output_device_id
        if selected and not self.audio_device_service.is_available(selected):
            self.settings.audio_output_device_id = ""
            self._apply_audio_output_device("")
            message = "선택한 오디오 장치가 분리되어 시스템 기본 출력으로 전환했습니다."
            LOGGER.warning(message)
            self.status.setText(message)
            return
        if not self._apply_audio_output_device(selected):
            self.settings.audio_output_device_id = ""
            self._apply_audio_output_device("")
            self.status.setText("오디오 출력 갱신 실패 · 시스템 기본 출력 사용")

    def _pdf_prepare_sizes(self) -> dict[ChannelRole, QSize]:
        if self.settings.simulation_mode:
            size = QSize(
                round(self.settings.simulation_width * self.settings.simulation_dpr),
                round(self.settings.simulation_height * self.settings.simulation_dpr),
            )
            return {ChannelRole.BROADCAST: size, ChannelRole.VENUE: QSize(size)}
        by_id = {screen.id: screen for screen in self.screen_service.screens()}
        broadcast = by_id.get(self.settings.broadcast_screen_id)
        venue = by_id.get(self.settings.venue_screen_id)
        return {
            ChannelRole.BROADCAST: QSize(
                round(broadcast.width * broadcast.device_pixel_ratio) if broadcast else 1920,
                round(broadcast.height * broadcast.device_pixel_ratio) if broadcast else 1080,
            ),
            ChannelRole.VENUE: QSize(
                round(venue.width * venue.device_pixel_ratio) if venue else 1920,
                round(venue.height * venue.device_pixel_ratio) if venue else 1080,
            ),
        }

    def _move_controller_to_assigned_screen(self) -> None:
        if not self.settings.controller_screen_id:
            return
        screen = self.screen_service.qt_screen(self.settings.controller_screen_id)
        if screen is None:
            self.status.setText("저장된 Controller 화면을 찾을 수 없습니다. 다시 지정하십시오.")
            return
        available = screen.availableGeometry()
        x = available.x() + max(0, (available.width() - self.width()) // 2)
        y = available.y() + max(0, (available.height() - self.height()) // 2)
        self.move(x, y)

    def start_outputs(self) -> bool:
        self.stop_outputs()
        if self.settings.simulation_mode:
            profile = (self.settings.simulation_width, self.settings.simulation_height)
            if self.settings.simulation_broadcast_connected:
                self.broadcast_simulator = SimulationWindow(
                    ChannelRole.BROADCAST,
                    self.coordinator,
                    profile,
                    self.settings.simulation_dpr,
                )
                self.broadcast_simulator.set_content(self.state.broadcast.live_content)
                self.broadcast_simulator.show()
            else:
                self._disconnect_role(ChannelRole.BROADCAST, "가상 Broadcast 화면 연결 해제")
            if self.settings.simulation_venue_connected:
                self.venue_simulator = SimulationWindow(
                    ChannelRole.VENUE,
                    self.coordinator,
                    profile,
                    self.settings.simulation_dpr,
                )
                self.venue_simulator.set_content(self.state.venue.live_content)
                self.venue_simulator.show()
            else:
                self._disconnect_role(ChannelRole.VENUE, "가상 Venue 화면 연결 해제")
            self.status.setText("Simulation Outputs 시작됨")
            self._restore_live_video_frames()
            return True

        valid, error = validate_role_assignment(
            self.settings.broadcast_screen_id,
            self.settings.venue_screen_id,
            simulation_mode=False,
        )
        if not valid:
            QMessageBox.warning(self, "출력 시작", error)
            return False
        broadcast_screen = self.screen_service.qt_screen(self.settings.broadcast_screen_id)
        venue_screen = self.screen_service.qt_screen(self.settings.venue_screen_id)
        if broadcast_screen is None or venue_screen is None:
            QMessageBox.warning(
                self,
                "출력 시작",
                "저장된 화면을 찾을 수 없습니다. 화면 역할을 다시 지정하십시오.",
            )
            return False
        self.broadcast_output = BroadcastOutputWindow(self.coordinator)
        self.venue_output = VenueOutputWindow(self.coordinator)
        self.broadcast_output.set_content(self.state.broadcast.live_content)
        self.venue_output.set_content(self.state.venue.live_content)
        self.broadcast_output.start_on_screen(broadcast_screen)
        self.venue_output.start_on_screen(venue_screen)
        self._restore_live_video_frames()
        self.status.setText("Physical Outputs 시작됨")
        return True

    def _ensure_live_outputs(self, roles: tuple[ChannelRole, ...]) -> bool:
        def is_active(role: ChannelRole) -> bool:
            window: QWidget | None
            if self.settings.simulation_mode:
                window = (
                    self.broadcast_simulator
                    if role is ChannelRole.BROADCAST
                    else self.venue_simulator
                )
            else:
                window = (
                    self.broadcast_output
                    if role is ChannelRole.BROADCAST
                    else self.venue_output
                )
            return window is not None and window.isVisible()

        if all(is_active(role) for role in roles):
            return True
        if not self.start_outputs() or not all(is_active(role) for role in roles):
            labels = ", ".join(role.value.title() for role in roles)
            self.status.setText(
                f"TAKE 실패 · {labels} 실제 출력 창을 시작할 수 없습니다. 기존 Live 유지"
            )
            return False
        return True

    def stop_outputs(self) -> None:
        for window in (
            self.broadcast_output,
            self.venue_output,
            self.broadcast_simulator,
            self.venue_simulator,
        ):
            if window is not None:
                window.safe_close()
        self.broadcast_output = None
        self.venue_output = None
        self.broadcast_simulator = None
        self.venue_simulator = None

    def _push_live(self, role: ChannelRole) -> None:
        content = self.state.channel(role).live_content
        fade = self.settings.fade_duration_ms
        if role is ChannelRole.BROADCAST:
            self.broadcast_live.set_content(content, fade)
            if self.broadcast_output:
                self.broadcast_output.set_content(content, fade)
            if self.broadcast_simulator:
                self.broadcast_simulator.set_content(content, fade)
        else:
            self.venue_live.set_content(content, fade)
            if self.venue_output:
                self.venue_output.set_content(content, fade)
            if self.venue_simulator:
                self.venue_simulator.set_content(content, fade)
        if content.kind is ContentType.VIDEO:
            path, frame = self.video_manager.last_live_frame(role)
            if path is not None and not frame.isNull():
                self._video_live_frame(role, str(path), frame)

    def _refresh_channel(self, role: ChannelRole) -> None:
        channel = self.state.channel(role)
        if role is ChannelRole.BROADCAST:
            self.broadcast_preview.set_content(channel.preview_content)
            self.broadcast_live.set_content(channel.live_content)
            self.take_broadcast.setEnabled(channel.is_ready)
        else:
            self.venue_preview.set_content(channel.preview_content)
            self.venue_live.set_content(channel.live_content)
            self.take_venue.setEnabled(channel.is_ready)

    def _refresh_all(self) -> None:
        self._refresh_channel(ChannelRole.BROADCAST)
        self._refresh_channel(ChannelRole.VENUE)
        self._update_screen_status()

    def _update_screen_status(self) -> None:
        mode = "Simulation" if self.settings.simulation_mode else "Physical"
        self.screen_status.setText(f"화면 {len(self.screen_service.screens())}개 · {mode} Mode")

    def _screens_changed(self) -> None:
        ids = {screen.id for screen in self.screen_service.screens()}
        if self.broadcast_output is not None and self.settings.broadcast_screen_id not in ids:
            self._disconnect_role(ChannelRole.BROADCAST, "Broadcast 출력 화면이 분리되었습니다.")
        if self.venue_output is not None and self.settings.venue_screen_id not in ids:
            self._disconnect_role(ChannelRole.VENUE, "Venue 출력 화면이 분리되었습니다.")
        self._update_screen_status()

    def _disconnect_role(self, role: ChannelRole, message: str) -> None:
        channel = self.state.channel(role)
        if channel.live_content.kind is ContentType.VIDEO:
            self.video_manager.clear_live(role)
        channel.preview_content = Content.black()
        channel.live_content = Content.black()
        channel.is_ready = True
        channel.last_error = message
        if role is ChannelRole.BROADCAST and self.broadcast_output:
            self.broadcast_output.safe_close()
            self.broadcast_output = None
        if role is ChannelRole.BROADCAST and self.broadcast_simulator:
            self.broadcast_simulator.safe_close()
            self.broadcast_simulator = None
        if role is ChannelRole.VENUE and self.venue_output:
            self.venue_output.safe_close()
            self.venue_output = None
        if role is ChannelRole.VENUE and self.venue_simulator:
            self.venue_simulator.safe_close()
            self.venue_simulator = None
        self._refresh_channel(role)
        self.status.setText(message + " 해당 채널을 BLACK으로 전환했습니다.")
        QMessageBox.warning(self, "화면 연결 해제", self.status.text())

    def _subtitle_document_changed(self, document: SubtitleDocument) -> None:
        self.settings.subtitle_group_size = document.group_size
        if document.path:
            self.settings.last_subtitle_file = str(document.path)
            self.settings.subtitle_folder = str(document.path.parent)

    def _pdf_folder_changed(self, folder: str) -> None:
        self.settings.pdf_folder = folder

    def _pdf_selection_changed(self, path: str, page: int) -> None:
        self.settings.last_pdf_file = path
        self.settings.last_pdf_page = page

    def _pdf_page_order_changed(self, path: str, order: object) -> None:
        if not isinstance(order, list):
            return
        normalized = [page for page in order if isinstance(page, int)]
        if len(normalized) == len(order):
            self.settings.pdf_page_orders[path] = normalized

    def _video_folder_changed(self, folder: str) -> None:
        self.settings.video_folder = folder

    def _audio_folder_changed(self, folder: str) -> None:
        self.settings.audio_folder = folder

    def _video_selection_changed(self, path: str) -> None:
        self.settings.last_video_file = path

    def _playlist_path_changed(self, path: str) -> None:
        self.settings.last_playlist = path
        if path and path not in self.settings.recent_playlists:
            self.settings.recent_playlists = [path, *self.settings.recent_playlists][:10]

    def _media_settings_changed(self) -> None:
        self.settings.video_sort_field = self.video_panel.sort_field
        self.settings.video_sort_descending = self.video_panel.descending
        self.settings.audio_sort_field = self.audio_panel.sort_field
        self.settings.audio_sort_descending = self.audio_panel.descending
        self.settings.video_volume = self.video_panel.volume_slider.value()
        self.settings.video_muted = self.video_panel.mute_check.isChecked()
        self.settings.fade_duration_ms = self.video_panel.fade_spin.value()
        self.settings.music_volume = self.audio_panel.volume_slider.value()
        self.settings.music_muted = self.audio_panel.mute_check.isChecked()
        self.settings.repeat_mode = self.audio_controller.playlist.repeat_mode

    def _video_preview_result(
        self,
        role: ChannelRole | str,
        path: str,
        image: QImage,
        error: str,
    ) -> None:
        role = self._normalize_role(role)
        content = self.state.channel(role).preview_content
        if (
            content.kind is not ContentType.VIDEO
            or content.video_path is None
            or content.video_path.expanduser().resolve() != Path(path).expanduser().resolve()
        ):
            return
        if not image.isNull():
            monitor = (
                self.broadcast_preview if role is ChannelRole.BROADCAST else self.venue_preview
            )
            monitor.surface.set_video_frame(path, image)
        self.video_panel.preview_result(role, path, image, error)
        self.mark_preview_ready(role, not error, error)

    def _video_live_frame(
        self,
        role: ChannelRole | str,
        path: str,
        image: QImage,
    ) -> None:
        role = self._normalize_role(role)
        surfaces = (
            (self.broadcast_live.surface,)
            if role is ChannelRole.BROADCAST
            else (self.venue_live.surface,)
        )
        for surface in surfaces:
            surface.set_video_frame(path, image)
        if role is ChannelRole.BROADCAST:
            if self.broadcast_output:
                self.broadcast_output.surface.set_video_frame(path, image)
            if self.broadcast_simulator:
                self.broadcast_simulator.surface.set_video_frame(path, image)
        else:
            if self.venue_output:
                self.venue_output.surface.set_video_frame(path, image)
            if self.venue_simulator:
                self.venue_simulator.surface.set_video_frame(path, image)

    def _restore_live_video_frames(self) -> None:
        for role in (ChannelRole.BROADCAST, ChannelRole.VENUE):
            path, frame = self.video_manager.last_live_frame(role)
            if path is not None and not frame.isNull():
                self._video_live_frame(role, str(path), frame)

    def _video_play_started(self, role: ChannelRole | str) -> None:
        role = self._normalize_role(role)
        target = (
            "Broadcast + Venue 영상 재생"
            if self.video_manager.is_live_transport_linked
            else f"{role.value.title()} 영상 재생"
        )
        if self.audio_controller.pause_for_video():
            self.status.setText(f"{target} · 배경음악을 자동 일시정지했습니다.")
        else:
            self.status.setText(f"{target} 시작")

    def _black_live(self, role: ChannelRole | str, message: str) -> None:
        role = self._normalize_role(role)
        channel = self.state.channel(role)
        channel.live_content = Content.black()
        self._push_live(role)
        self._refresh_channel(role)
        self.status.setText(message)

    @staticmethod
    def _is_within(widget: QWidget | None, container: QWidget) -> bool:
        return widget is container or (widget is not None and container.isAncestorOf(widget))

    def _focus_changed(self, _previous: QWidget | None, current: QWidget | None) -> None:
        active = self._is_within(current, self.sync_bar)
        self.sync_bar.setProperty("keyboardActive", active)
        style = self.sync_bar.style()
        style.unpolish(self.sync_bar)
        style.polish(self.sync_bar)
        self.sync_bar.update()

    def _keyboard_area(self, focus: QWidget | None) -> str | None:
        if focus is None or (focus is not self and not self.isAncestorOf(focus)):
            return None
        if self._is_within(focus, self.sync_bar):
            return "linked"
        if self._is_within(focus, self.subtitle_panel):
            return "subtitle"
        if self._is_within(focus, self.pdf_panel):
            return "pdf"
        if self._is_within(focus, self.video_panel):
            return "video"
        if self._is_within(focus, self.audio_panel):
            return "audio"
        if self._is_within(focus, self.tabs) or focus is self:
            panel = self.tabs.currentWidget()
            if panel is self.subtitle_panel:
                return "subtitle"
            if panel is self.pdf_panel:
                return "pdf"
            if panel is self.video_panel:
                return "video"
            if panel is self.audio_panel:
                return "audio"
        return None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() is QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and self._handle_navigation_key(
                event,
                watched if isinstance(watched, QWidget) else None,
            )
        ):
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def _handle_navigation_key(
        self,
        event: QKeyEvent,
        event_target: QWidget | None = None,
    ) -> bool:
        focus = event_target or self.application.focusWidget()
        if isinstance(focus, (QLineEdit, QAbstractSpinBox, QComboBox, QSlider)):
            return False
        area = self._keyboard_area(focus)
        if area is None:
            return False
        if area != "linked" and isinstance(focus, QAbstractButton):
            return False
        key = event.key()
        if area == "linked":
            if key == Qt.Key.Key_Left:
                self.move_linked_previews(-1)
            elif key == Qt.Key.Key_Right:
                self.move_linked_previews(1)
            elif key == Qt.Key.Key_Home:
                self.first_linked_previews()
            elif key == Qt.Key.Key_End:
                self.last_linked_previews()
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.take_linked_previews()
            else:
                return False
            return True
        if area == "subtitle":
            if key == Qt.Key.Key_Left:
                self.subtitle_panel.move_preview(-1)
            elif key == Qt.Key.Key_Right:
                self.subtitle_panel.move_preview(1)
            elif key == Qt.Key.Key_Home:
                self.subtitle_panel.navigate(0)
            elif key == Qt.Key.Key_End:
                self.subtitle_panel.navigate(len(self.subtitle_panel.document.cards) - 1)
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.take(ChannelRole.BROADCAST)
            else:
                return False
            return True
        if area == "pdf":
            if key == Qt.Key.Key_Left:
                self.pdf_panel.move_preview(-1)
            elif key == Qt.Key.Key_Right:
                self.pdf_panel.move_preview(1)
            elif key == Qt.Key.Key_Home:
                self.pdf_panel.navigate_first()
            elif key == Qt.Key.Key_End:
                self.pdf_panel.navigate_last()
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self.pdf_panel.link_outputs:
                    self.take_both()
                else:
                    self.take(self.pdf_panel.target_role)
            else:
                return False
            return True
        if area == "video":
            role = self.video_panel.target_role
            runtime = self.video_manager.runtime(role)
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.take(role)
            elif key == Qt.Key.Key_Space:
                if runtime.status is PlaybackStatus.PLAYING:
                    self.video_manager.pause(role)
                else:
                    self.video_manager.play(role)
            elif key == Qt.Key.Key_S:
                self.video_manager.stop(role)
            elif key == Qt.Key.Key_Home:
                self.video_manager.restart(role)
            elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                row = self.video_panel.file_list.currentRow()
                offset = -1 if key == Qt.Key.Key_Left else 1
                target = max(0, min(self.video_panel.file_list.count() - 1, row + offset))
                if target >= 0:
                    self.video_panel.file_list.setCurrentRow(target)
            else:
                return False
            return True
        if area == "audio":
            control = bool(
                event.modifiers()
                & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
            )
            if key == Qt.Key.Key_Space:
                if self.audio_controller.runtime.status is PlaybackStatus.PLAYING:
                    self.audio_controller.pause(PauseReason.USER)
                else:
                    self.audio_controller.play()
            elif control and key == Qt.Key.Key_Right:
                self.audio_controller.next()
            elif control and key == Qt.Key.Key_Left:
                self.audio_controller.previous()
            else:
                return False
            return True
        return False

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._handle_navigation_key(event, self):
            super().keyPressEvent(event)

    def _persist_settings(self) -> None:
        self.settings.sort_field = self.pdf_panel.sort_field
        self.settings.sort_descending = self.pdf_panel.descending
        self._media_settings_changed()
        self.settings.audio_position_ms = self.audio_controller.runtime.position_ms
        current_audio = self.audio_controller.playlist.current_item
        self.settings.last_audio_file = str(current_audio.path) if current_audio else ""
        self.settings.panel_layout = f"tabs:{self.tabs.currentIndex()}"
        geometry_data = self.saveGeometry().toBase64().data()
        self.settings.controller_geometry = bytes(geometry_data).decode("ascii")
        self.settings_service.save(self.settings)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._closing:
            event.accept()
            return
        if not self.subtitle_panel.confirm_discard_changes():
            event.ignore()
            return
        if not self.audio_panel.confirm_discard_changes():
            event.ignore()
            return
        self._closing = True
        try:
            self.state.black_all()
            self._refresh_all()
            self._push_live(ChannelRole.BROADCAST)
            self._push_live(ChannelRole.VENUE)
            self.application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
            self.video_manager.close()
            self.audio_controller.close()
            self.stop_outputs()
            self._persist_settings()
        except Exception:
            LOGGER.exception("Error during safe shutdown")
            self.stop_outputs()
        self.application.removeEventFilter(self)
        event.accept()
