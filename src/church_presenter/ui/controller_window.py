from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QByteArray, QEvent, QEventLoop, QObject, QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QImage, QKeyEvent, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from church_presenter.domain.enums import ChannelRole, ContentType, PauseReason, PlaybackStatus
from church_presenter.domain.models import (
    AppSettings,
    Content,
    PreviewPreset,
    SubtitleStyle,
    default_bible_reference_style,
)
from church_presenter.domain.state import ApplicationState
from church_presenter.media.audio_controller import AudioPlaybackController
from church_presenter.media.base import MediaPlaybackBackend
from church_presenter.media.mpv_audio_backend import MpvAudioBackend
from church_presenter.media.playlist import PlaylistService
from church_presenter.media.qt_media_backend import QtMediaBackend
from church_presenter.media.video_manager import VideoPlaybackManager
from church_presenter.remote.frame_capture import FrameCaptureService
from church_presenter.remote.input_dispatcher import RemoteInputDispatcher
from church_presenter.remote.network_service import RemoteNetworkService
from church_presenter.rendering.output_surface import AspectRatioContainer, OutputSurface
from church_presenter.services.audio_device_service import AudioDeviceService
from church_presenter.services.bible_service import BibleRepository
from church_presenter.services.pdf_service import PdfRenderCoordinator, pdf_page_count
from church_presenter.services.screen_service import ScreenService, validate_role_assignment
from church_presenter.services.settings_service import SettingsService
from church_presenter.services.transition_service import FIXED_OUTPUT_FADE_DURATION_MS
from church_presenter.ui.dialogs.remote_connection_dialog import RemoteConnectionDialog
from church_presenter.ui.dialogs.screen_settings_dialog import ScreenSettingsDialog
from church_presenter.ui.dialogs.subtitle_style_dialog import SubtitleStyleDialog
from church_presenter.ui.labels import channel_label
from church_presenter.ui.output_window import BroadcastOutputWindow, VenueOutputWindow
from church_presenter.ui.panels.audio_panel import AudioPanel
from church_presenter.ui.panels.bible_panel import BiblePanel
from church_presenter.ui.panels.black_panel import BlackPanel
from church_presenter.ui.panels.instant_panel import InstantPanel
from church_presenter.ui.panels.misc_panel import MiscPanel
from church_presenter.ui.panels.pdf_panel import PdfPanel
from church_presenter.ui.panels.preview_preset_panel import PreviewPresetPanel
from church_presenter.ui.panels.subtitle_panel import SubtitlePanel
from church_presenter.ui.panels.video_panel import VideoPanel
from church_presenter.ui.simulation_window import SimulationWindow
from church_presenter.ui.styles import DEFAULT_THEME_ID, ThemeManager

LOGGER = logging.getLogger(__name__)
CONTROLLER_DESIGN_SIZE = QSize(1920, 1080)
CONTROLLER_DEFAULT_SIZE = QSize(1600, 900)
CONTROLLER_MINIMUM_SIZE = QSize(800, 600)
COMPACT_HEADER_WIDTH = 1100
COMPACT_DENSITY_WIDTH = 1440
COMPACT_DENSITY_HEIGHT = 900
BROADCAST_CHROMA_CONTENT = Content.solid_color("#00FF00")


class ChannelMonitor(QFrame):
    """Labelled 16:9 Controller mirror for Preview or Live."""

    def __init__(
        self,
        channel_name: str,
        coordinator: PdfRenderCoordinator,
        live: bool,
    ) -> None:
        super().__init__()
        state_role = "live" if live else "preview"
        state_name = "LIVE" if live else "PREVIEW"
        self.setObjectName("LiveMonitor" if live else "PreviewMonitor")
        self.setProperty("stateRole", state_role)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header_frame = QFrame()
        header_frame.setObjectName("MonitorHeader")
        header_frame.setProperty("stateRole", state_role)
        self.header_layout = QHBoxLayout(header_frame)
        self.header_layout.setContentsMargins(12, 8, 12, 8)
        self.header_layout.setSpacing(8)
        self.state_label = QLabel(state_name)
        self.state_label.setObjectName("MonitorState")
        self.state_label.setProperty("stateRole", state_role)
        self.title = QLabel(channel_name)
        self.title.setProperty("role", "secondary")
        self.mode = QLabel("BLACK")
        self.mode.setObjectName("ContentTypeBadge")
        self.header_layout.addWidget(self.state_label)
        self.header_layout.addWidget(self.title)
        self.header_layout.addStretch()
        self.header_layout.addWidget(self.mode)
        layout.addWidget(header_frame)

        content_frame = QFrame()
        self.content_layout = QVBoxLayout(content_frame)
        self.content_layout.setContentsMargins(12, 10, 12, 12)
        self.surface = OutputSurface(coordinator)
        self.surface.setMinimumSize(160, 90)
        self.container = AspectRatioContainer(self.surface)
        self.container.setMinimumSize(160, 90)
        self.content_layout.addWidget(self.container, 1)
        layout.addWidget(content_frame, 1)
        self._compact = False

    def set_compact(self, compact: bool) -> None:
        """Reduce only monitor chrome when vertical workspace is constrained."""
        if compact == self._compact:
            return
        self._compact = compact
        if compact:
            self.header_layout.setContentsMargins(8, 4, 8, 4)
            self.content_layout.setContentsMargins(8, 4, 8, 6)
            self.surface.setMinimumSize(64, 36)
            self.container.setMinimumSize(64, 36)
        else:
            self.header_layout.setContentsMargins(12, 8, 12, 8)
            self.content_layout.setContentsMargins(12, 10, 12, 12)
            self.surface.setMinimumSize(160, 90)
            self.container.setMinimumSize(160, 90)

    def set_content(self, content: Content, fade_duration_ms: int = 0) -> None:
        mode = "BLANK" if content.kind is ContentType.SOLID_COLOR else content.kind.value.upper()
        self.mode.setText(mode)
        if content != self.surface.target_content:
            self.surface.set_content(content, fade_duration_ms)


class ResponsiveContentTabs(QTabWidget):
    """Allow the lower workspace to compress without an outer scroll range."""

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)


class PersistentDockWidget(QDockWidget):
    """A movable/floating dock whose operator content cannot be closed."""

    def closeEvent(self, event: QCloseEvent) -> None:
        parent = self.parentWidget()
        if parent is not None and bool(getattr(parent, "_closing", False)):
            event.accept()
            return
        event.ignore()
        self.show()


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
        theme_manager: ThemeManager | None = None,
    ) -> None:
        super().__init__()
        self.setDockOptions(self.dockOptions() & ~QMainWindow.DockOption.AnimatedDocks)
        self.setObjectName("ControllerWindow")
        self.application = application
        self.screen_service = screen_service
        self.settings_service = settings_service
        self.settings = settings
        self.settings.fade_duration_ms = FIXED_OUTPUT_FADE_DURATION_MS
        self.bible_repository: BibleRepository | None = None
        self.bible_path: Path | None = None
        if settings.bible_file:
            candidate_bible = Path(settings.bible_file).expanduser()
            if candidate_bible.is_file():
                try:
                    self.bible_repository = BibleRepository.load(candidate_bible)
                    self.bible_path = candidate_bible.resolve()
                except (OSError, UnicodeError, KeyError, TypeError, ValueError):
                    LOGGER.exception("Could not restore Bible JSON")
        if self.bible_repository is None:
            try:
                self.bible_repository = BibleRepository.load_bundled()
                self.bible_path = Path(
                    "src/church_presenter/assets/bibles/new_korean_translation.json"
                ).resolve()
            except (
                OSError,
                UnicodeError,
                KeyError,
                ModuleNotFoundError,
                TypeError,
                ValueError,
            ):
                pass
        self.theme_manager = theme_manager or ThemeManager()
        if not self.theme_manager.current_theme_id():
            applied_theme = self.theme_manager.apply_theme(application, settings.current_theme)
            self.settings.current_theme = applied_theme or DEFAULT_THEME_ID
        self.preview_presets, self._preview_preset_warning = (
            self.settings_service.load_preview_presets()
        )
        self.preview_preset_file: Path | None = None
        if settings.preview_preset_file:
            candidate = Path(settings.preview_preset_file).expanduser()
            if candidate.is_file():
                try:
                    self.preview_presets = self.settings_service.load_preview_preset_file(candidate)
                    self.preview_preset_file = candidate.resolve()
                except (OSError, UnicodeError, KeyError, ValueError, TypeError) as error:
                    LOGGER.exception("Could not restore worship-order file")
                    self._preview_preset_warning = (
                        f"예배 순서 파일을 열 수 없어 App Data 목록을 사용합니다: {error}"
                    )
            else:
                self._preview_preset_warning = (
                    "저장된 예배 순서 파일을 찾을 수 없어 App Data 목록을 사용합니다."
                )
                settings.preview_preset_file = ""
        self.state = ApplicationState()
        self.coordinator = PdfRenderCoordinator()
        self._preview_preset_pdf_requests: dict[ChannelRole, object] = {}
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
        self.audio_controller = AudioPlaybackController(
            audio_backend
            or QtMediaBackend(
                video=False,
                audio_device_resolver=self.audio_device_service.resolve,
            ),
            streaming_backend=MpvAudioBackend(
                audio_device_resolver=self.audio_device_service.resolve,
            ),
            volume=settings.music_volume / 100,
            muted=settings.music_muted,
        )
        self.audio_controller.playlist.repeat_mode = settings.repeat_mode
        self._audio_startup_warning = ""
        if not self._apply_audio_output_device(settings.audio_output_device_id):
            settings.audio_output_device_id = ""
            self._apply_audio_output_device("")
            self._audio_startup_warning = (
                "저장된 오디오 출력 장치를 찾을 수 없어 시스템 기본 출력으로 전환했습니다."
            )
        self.broadcast_output: BroadcastOutputWindow | None = None
        self.venue_output: VenueOutputWindow | None = None
        self.broadcast_simulator: SimulationWindow | None = None
        self.venue_simulator: SimulationWindow | None = None
        self._closing = False
        self._ui_density = ""
        self._linked_auto_take_pending = False
        self._linked_auto_take_snapshot: tuple[Content, Content] | None = None
        self.setWindowTitle("Church Presenter")
        self.setMinimumSize(CONTROLLER_MINIMUM_SIZE)
        self.resize(CONTROLLER_DEFAULT_SIZE)
        if settings.controller_geometry:
            try:
                self.restoreGeometry(
                    QByteArray.fromBase64(settings.controller_geometry.encode("ascii"))
                )
            except (ValueError, UnicodeError):
                LOGGER.exception("Could not restore Controller geometry")
        self._build_ui()
        self.remote_service = RemoteNetworkService(self)
        self.frame_capture = FrameCaptureService(
            self.application,
            self,
            excluded=lambda widget: bool(widget.property("remoteConnectionDialog")),
            parent=self,
        )
        self.remote_input_dispatcher = RemoteInputDispatcher(
            lambda: self.frame_capture.current_target or self,
            self,
        )
        self.remote_connection_dialog: RemoteConnectionDialog | None = None
        self.remote_service.client_count_changed.connect(self.frame_capture.set_client_count)
        self.remote_service.input_received.connect(
            self.remote_input_dispatcher.dispatch,
            Qt.ConnectionType.QueuedConnection,
        )
        self.remote_service.state_changed.connect(self._remote_state_changed)
        self.frame_capture.frame_ready.connect(self.remote_service.publish_frame)
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
        if self._preview_preset_warning:
            self.status.setText(self._preview_preset_warning)
        if settings_warning:
            self.status.setText(settings_warning)
        if previous_unclean_exit:
            self.status.setText(
                "이전 실행이 정상 종료되지 않았습니다. 출력 상태는 안전하게 BLACK입니다."
            )

    def _build_ui(self) -> None:
        self.root_scroll = QScrollArea()
        self.root_scroll.setObjectName("ControllerScroll")
        self.root_scroll.setWidgetResizable(True)
        root = QWidget()
        self.root_scroll.setWidget(root)
        self.setCentralWidget(self.root_scroll)
        layout = QVBoxLayout(root)
        self.root_layout = layout
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)

        header_frame = QFrame()
        header_frame.setObjectName("AppHeader")
        top = QGridLayout(header_frame)
        top.setContentsMargins(16, 10, 16, 10)
        top.setHorizontalSpacing(16)
        top.setVerticalSpacing(4)
        self.header_layout = top
        self.header_title_widget = QWidget()
        title_block = QVBoxLayout(self.header_title_widget)
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(2)
        self.app_title = QLabel("Church Presenter")
        self.app_title.setProperty("role", "pageTitle")
        self.byline = QLabel("by Jinsol")
        self.byline.setProperty("role", "secondary")
        self.screen_status = QLabel("화면 상태 확인 중")
        self.screen_status.setProperty("role", "secondary")
        self.title_row = QHBoxLayout()
        self.title_row.setContentsMargins(0, 0, 0, 0)
        self.title_row.setSpacing(6)
        self.title_row.addWidget(self.app_title)
        self.title_row.addWidget(self.byline)
        self.title_row.addStretch()
        title_block.addLayout(self.title_row)
        title_block.addWidget(self.screen_status)

        self.status = QLabel("준비됨 · 모든 Live는 BLACK")
        self.status.setWordWrap(False)
        settings_button = QPushButton("화면 / 오디오 설정")
        settings_button.setProperty("variant", "secondary")
        self.remote_connection_button = QPushButton("원격 연결")
        self.remote_connection_button.setProperty("variant", "secondary")
        self.start_outputs_button = QPushButton("출력 시작")
        self.start_outputs_button.setProperty("variant", "primary")
        self.stop_outputs_button = QPushButton("출력 중지")
        self.stop_outputs_button.setProperty("variant", "secondary")

        appearance_label = QLabel("테마")
        appearance_label.setProperty("role", "secondary")
        self.theme_combo = QComboBox()
        self.theme_combo.setAccessibleName("애플리케이션 테마")
        self.theme_combo.setToolTip("Controller UI 테마를 즉시 변경하고 저장합니다.")
        for theme in self.theme_manager.available_themes():
            self.theme_combo.addItem(theme.name, theme.id)
        theme_index = self.theme_combo.findData(self.settings.current_theme)
        self.theme_combo.setCurrentIndex(max(0, theme_index))

        self.header_actions_widget = QWidget()
        actions = QGridLayout(self.header_actions_widget)
        self.header_actions_layout = actions
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.header_action_widgets = (
            appearance_label,
            self.theme_combo,
            settings_button,
            self.remote_connection_button,
            self.start_outputs_button,
            self.stop_outputs_button,
        )
        for column, widget in enumerate(self.header_action_widgets):
            actions.addWidget(widget, 0, column)
        top.setColumnStretch(0, 1)
        self._compact_header: bool | None = None
        self._update_header_layout(self.width())
        layout.addWidget(header_frame)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addWidget(self.status, 1)

        self.workspace_splitter = QSplitter(Qt.Orientation.Vertical)
        self.workspace_splitter.setObjectName("WorkspaceSplitter")
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(6)
        self.monitor_workspace = QWidget()
        self.monitor_workspace.setObjectName("MonitorWorkspace")
        self.monitor_workspace_layout = QVBoxLayout(self.monitor_workspace)
        self.monitor_workspace_layout.setContentsMargins(0, 0, 0, 0)
        self.monitor_workspace_layout.setSpacing(12)
        self.monitor_grid = QGridLayout()
        self.monitor_grid.setContentsMargins(0, 0, 0, 0)
        self.monitor_grid.setHorizontalSpacing(12)
        self.monitor_grid.setVerticalSpacing(12)
        self.broadcast_preview = ChannelMonitor("송출", self.coordinator, False)
        self.broadcast_live = ChannelMonitor("송출", self.coordinator, True)
        self.venue_preview = ChannelMonitor("현장", self.coordinator, False)
        self.venue_live = ChannelMonitor("현장", self.coordinator, True)
        self.monitor_grid.addWidget(self.broadcast_preview, 0, 0)
        self.monitor_grid.addWidget(self.broadcast_live, 0, 1)
        self.monitor_grid.addWidget(self.venue_preview, 1, 0)
        self.monitor_grid.addWidget(self.venue_live, 1, 1)
        self.monitor_grid.setRowStretch(0, 1)
        self.monitor_grid.setRowStretch(1, 1)
        self.monitor_workspace_layout.addLayout(self.monitor_grid, 1)

        self.sync_bar = QFrame()
        self.sync_bar.setObjectName("SyncControl")
        self.sync_bar.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.sync_bar.setToolTip(
            "이 영역에 포커스가 있으면 화살표 또는 PageUp/PageDown으로 함께 이동하고 "
            "Enter로 TAKE BOTH를 실행합니다. 바로 Live가 켜지면 이동 후 자동 TAKE합니다."
        )
        sync_layout = QHBoxLayout(self.sync_bar)
        self.sync_layout = sync_layout
        sync_layout.setContentsMargins(14, 10, 14, 10)
        sync_layout.setSpacing(8)
        self.sync_title = QLabel("연동 제어")
        self.sync_title.setProperty("role", "sectionTitle")
        self.sync_content_check = QCheckBox("동시 진행")
        self.sync_content_check.setObjectName("SyncContentCheck")
        self.sync_content_check.setChecked(self.settings.subtitle_pdf_linked)
        self.sync_auto_take_check = QCheckBox("바로 Live")
        self.sync_auto_take_check.setObjectName("LinkedAutoTakeCheck")
        self.sync_auto_take_check.setChecked(self.settings.linked_navigation_auto_take)
        self.sync_auto_take_check.setToolTip(
            "이전/다음 입력 후 두 Preview가 준비되면 TAKE BOTH를 자동 실행합니다."
        )
        self.sync_chroma_check = QCheckBox("크로마키")
        self.sync_chroma_check.setObjectName("BroadcastChromaCheck")
        self.sync_chroma_check.setToolTip(
            "송출 화면과 송출 LIVE를 크로마키 그린으로 가립니다. "
            "해제하면 가장 최근에 TAKE한 송출 Live를 표시합니다."
        )
        self.sync_previous_button = QPushButton("◀ 함께 이전")
        self.sync_previous_button.setProperty("variant", "ghost")
        self.sync_next_button = QPushButton("함께 다음 ▶")
        self.sync_next_button.setProperty("variant", "ghost")
        self.sync_take_button = QPushButton("TAKE BOTH")
        self.sync_take_button.setObjectName("LinkedTakeBoth")
        self.sync_take_button.setProperty("variant", "take")
        sync_layout.addWidget(self.sync_title)
        sync_layout.addStretch()
        sync_layout.addWidget(self.sync_content_check)
        sync_layout.addSpacing(20)
        sync_widgets: tuple[QWidget, ...] = (
            self.sync_auto_take_check,
            self.sync_chroma_check,
            self.sync_previous_button,
            self.sync_next_button,
            self.sync_take_button,
        )
        for sync_widget in sync_widgets:
            sync_layout.addWidget(sync_widget)
        self.monitor_workspace_layout.addWidget(self.sync_bar)
        self.workspace_splitter.addWidget(self.monitor_workspace)

        presets, default_preset, warning = self.settings_service.load_presets()
        preset_name = (
            self.settings.current_style_preset
            if self.settings.current_style_preset in presets
            else default_preset
        )
        self.subtitle_style = presets[preset_name]
        self.praise_style = (
            SubtitleStyle.from_dict(self.settings.praise_style)
            if self.settings.praise_style
            else self.subtitle_style
        )
        self.bible_style = (
            SubtitleStyle.from_dict(self.settings.bible_style)
            if self.settings.bible_style
            else self.subtitle_style
        )
        self.bible_reference_style = (
            SubtitleStyle.from_dict(self.settings.bible_reference_style)
            if self.settings.bible_reference_style
            else default_bible_reference_style()
        )
        self.instant_text_style = (
            SubtitleStyle.from_dict(self.settings.instant_text_style)
            if self.settings.instant_text_style
            else self.subtitle_style
        )
        if warning:
            self.status.setText(warning)
        self.tabs = ResponsiveContentTabs()
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.subtitle_panel = SubtitlePanel(
            self.praise_style,
            self.settings.praise_key_color,
            self.settings.subtitle_group_size,
            Path(self.settings.song_folder) if self.settings.song_folder else None,
        )
        self.praise_panel = self.subtitle_panel
        self.bible_panel = BiblePanel(
            self.bible_style,
            self.bible_reference_style,
            self.settings.bible_key_color,
            self.settings.bible_group_size,
            self.bible_repository,
            self.bible_path,
        )
        self.instant_panel = InstantPanel(
            self.instant_text_style,
            self.settings.instant_text_key_color,
            self.settings.instant_text_group_size,
        )
        self.black_panel = BlackPanel()
        self.misc_panel = MiscPanel(self.instant_panel, self.black_panel)
        self.subtitle_sources = {
            "instant": self.instant_panel,
            "praise": self.subtitle_panel,
            "bible": self.bible_panel,
        }
        self._apply_subtitle_card_theme()
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
        self.video_panel = VideoPanel(
            self.video_manager,
            Path(self.settings.video_folder) if self.settings.video_folder else None,
            self.settings.video_sort_field,
            self.settings.video_sort_descending,
            self.settings.video_volume,
            self.settings.video_muted,
            Path(self.settings.last_video_file) if self.settings.last_video_file else None,
        )
        self.audio_panel = AudioPanel(
            self.audio_controller,
            self.playlist_service,
            Path(self.settings.audio_folder) if self.settings.audio_folder else None,
            self.settings.audio_sort_field,
            self.settings.audio_sort_descending,
        )
        self._apply_audio_playlist_theme()
        for panel, source_id, label in (
            (self.subtitle_panel, "praise", "찬양"),
            (self.bible_panel, "bible", "성경"),
            (self.pdf_panel, "pdf", "PDF"),
            (self.video_panel, "video", "영상"),
            (self.audio_panel, "audio", "음악"),
            (self.misc_panel, "misc", "기타"),
        ):
            panel.setObjectName(f"ContentSource_{source_id}")
            self.tabs.addTab(panel, label)
        self.tabs.setMinimumHeight(0)
        self.tabs.currentChanged.connect(self._content_tab_changed)
        self.pdf_panel.set_compact_actions(self.width() < 1100)
        self.content_scroll = QScrollArea()
        self.content_scroll.setObjectName("ContentPanelScroll")
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_scroll.setMinimumHeight(170)
        self.content_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        self.content_scroll.setWidget(self.tabs)
        self.workspace_splitter.addWidget(self.content_scroll)
        self.workspace_splitter.setStretchFactor(0, 3)
        self.workspace_splitter.setStretchFactor(1, 2)
        self._workspace_splitter_user_adjusted = False
        self._workspace_splitter_state_restored = False
        self.workspace_splitter.splitterMoved.connect(self._workspace_splitter_moved)
        layout.addWidget(self.workspace_splitter, 1)

        self.preview_preset_panel = PreviewPresetPanel(self.preview_presets)
        self.preview_preset_panel.set_file_path(
            str(self.preview_preset_file) if self.preview_preset_file else ""
        )
        self.preview_preset_dock = PersistentDockWidget("예배 순서", self)
        self.preview_preset_dock.setObjectName("PreviewPresetDock")
        self.preview_preset_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.preview_preset_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.preview_preset_dock.setWidget(self.preview_preset_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.preview_preset_dock)
        self.preview_preset_dock.visibilityChanged.connect(self._schedule_scroll_fit)
        self.preview_preset_dock.visibilityChanged.connect(self._preview_preset_visibility_changed)

        settings_button.clicked.connect(self.open_screen_settings)
        self.remote_connection_button.clicked.connect(self._show_remote_connection)
        self.start_outputs_button.clicked.connect(self.start_outputs)
        self.stop_outputs_button.clicked.connect(self.stop_outputs)
        self.theme_combo.currentIndexChanged.connect(self._theme_selected)

    def _schedule_scroll_fit(self, _visible: bool) -> None:
        """Settle dock-driven central geometry within the same event-loop cycle."""
        QTimer.singleShot(0, self._fit_scroll_content)

    def _content_tab_changed(self, _index: int) -> None:
        panel = self.tabs.currentWidget()
        if panel is self.subtitle_panel:
            self.subtitle_panel.restore_preview()
        elif panel is self.bible_panel:
            self.bible_panel.restore_preview()

    def _preview_preset_visibility_changed(self, visible: bool) -> None:
        if not visible and not self._closing and self.isVisible():
            QTimer.singleShot(0, self._enforce_preview_preset_dock_visible)

    def _enforce_preview_preset_dock_visible(self) -> None:
        """Override restored/programmatic hidden states for the worship-order dock."""
        if self._closing:
            return
        self.preview_preset_dock.show()
        self.preview_preset_dock.setVisible(True)

    def _fit_scroll_content(self) -> None:
        root = self.root_scroll.widget()
        if root is None:
            return
        minimum = root.minimumSizeHint()
        viewport = self.root_scroll.viewport().size()
        root.resize(
            max(minimum.width(), viewport.width()),
            max(minimum.height(), viewport.height()),
        )
        self.root_layout.activate()

    def _workspace_splitter_moved(self, _position: int, _index: int) -> None:
        """Remember that the operator intentionally changed the workspace ratio."""
        self._workspace_splitter_user_adjusted = True

    def _apply_default_workspace_split(self) -> None:
        """Give output monitoring priority until the operator moves the splitter."""
        if self._workspace_splitter_user_adjusted or self._workspace_splitter_state_restored:
            return
        total = self.workspace_splitter.height()
        if total <= 0:
            return
        lower_minimum = 190 if self._ui_density == "compact" else 260
        upper = max(300, round(total * 0.60))
        lower = max(lower_minimum, total - upper)
        upper = max(0, total - lower)
        self.workspace_splitter.blockSignals(True)
        self.workspace_splitter.setSizes([upper, lower])
        self.workspace_splitter.blockSignals(False)

    def _apply_ui_density(self, size: QSize) -> None:
        """Automatically switch Controller chrome between normal and compact density."""
        compact = size.width() < COMPACT_DENSITY_WIDTH or size.height() <= COMPACT_DENSITY_HEIGHT
        density = "compact" if compact else "normal"
        self.sync_title.setVisible(size.width() >= 1000)
        narrow_sync_controls = size.width() < 900
        self.sync_previous_button.setText("◀ 이전" if narrow_sync_controls else "◀ 함께 이전")
        self.sync_next_button.setText("다음 ▶" if narrow_sync_controls else "함께 다음 ▶")
        if density == self._ui_density:
            return
        self._ui_density = density
        self.setProperty("uiDensity", density)
        if compact:
            self.root_layout.setContentsMargins(8, 6, 8, 4)
            self.root_layout.setSpacing(8)
            self.monitor_workspace_layout.setSpacing(8)
            self.monitor_grid.setHorizontalSpacing(8)
            self.monitor_grid.setVerticalSpacing(8)
            self.sync_layout.setContentsMargins(8, 4, 8, 4)
            self.content_scroll.setMinimumHeight(170)
        else:
            self.root_layout.setContentsMargins(16, 16, 16, 12)
            self.root_layout.setSpacing(12)
            self.monitor_workspace_layout.setSpacing(12)
            self.monitor_grid.setHorizontalSpacing(12)
            self.monitor_grid.setVerticalSpacing(12)
            self.sync_layout.setContentsMargins(14, 10, 14, 10)
            self.content_scroll.setMinimumHeight(220)
        for monitor in (
            self.broadcast_preview,
            self.broadcast_live,
            self.venue_preview,
            self.venue_live,
        ):
            monitor.set_compact(compact)
        self.pdf_panel.set_compact_mode(compact)
        self.video_panel.set_compact_mode(compact)
        self.audio_panel.set_compact_mode(compact)
        widgets = (self, *self.findChildren(QWidget))
        for widget in widgets:
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)
            widget.updateGeometry()
        self.root_layout.invalidate()
        QTimer.singleShot(0, self._apply_default_workspace_split)
        QTimer.singleShot(0, self._fit_scroll_content)

    def _update_header_layout(self, width: int) -> None:
        """Use one FHD row or two compact rows without duplicating controls."""
        compact = width < COMPACT_HEADER_WIDTH
        if compact != self._compact_header:
            self._compact_header = compact
            self.header_layout.removeWidget(self.header_title_widget)
            self.header_layout.removeWidget(self.header_actions_widget)
            for widget in self.header_action_widgets:
                self.header_actions_layout.removeWidget(widget)
            if compact:
                for index, compact_widget in enumerate(self.header_action_widgets):
                    self.header_actions_layout.addWidget(
                        compact_widget,
                        index // 3,
                        index % 3,
                    )
                self.header_layout.addWidget(self.header_title_widget, 0, 0, 1, 2)
                self.header_layout.addWidget(self.header_actions_widget, 1, 0, 1, 2)
            else:
                for column, regular_widget in enumerate(self.header_action_widgets):
                    self.header_actions_layout.addWidget(regular_widget, 0, column)
                self.header_layout.addWidget(self.header_title_widget, 0, 0)
                self.header_layout.addWidget(self.header_actions_widget, 0, 1)

    def _theme_selected(self, index: int) -> None:
        """Apply and persist a theme without changing presentation state."""
        theme_id = self.theme_combo.itemData(index)
        if not isinstance(theme_id, str) or not theme_id:
            return
        applied = self.theme_manager.apply_theme(self.application, theme_id)
        if not applied:
            self.status.setText(self.theme_manager.last_warning)
            return
        self._apply_subtitle_card_theme()
        self._apply_audio_playlist_theme()
        self.settings.current_theme = applied
        if applied != theme_id:
            fallback_index = self.theme_combo.findData(applied)
            if fallback_index >= 0:
                self.theme_combo.blockSignals(True)
                self.theme_combo.setCurrentIndex(fallback_index)
                self.theme_combo.blockSignals(False)
        try:
            self.settings_service.save(self.settings)
        except OSError as error:
            LOGGER.exception("Could not persist selected theme")
            self.status.setText(f"테마는 적용했지만 설정을 저장하지 못했습니다: {error}")
            return
        self.status.setText(
            self.theme_manager.last_warning or f"테마 적용 완료 · {self.theme_combo.currentText()}"
        )

    def _apply_subtitle_card_theme(self) -> None:
        """Keep item-level brushes aligned with the active JSON theme."""
        accent = str(self.theme_manager.current_value("colors", "accent"))
        self.subtitle_panel.set_card_theme(
            live_background=str(self.theme_manager.current_value("colors", "live")),
            preview_background=accent,
            text=str(self.theme_manager.current_value("colors", "text_primary")),
            active_text=str(self.theme_manager.current_value("colors", "text_on_accent")),
        )
        self.subtitle_panel.set_group_header_color(accent)
        self.bible_panel.set_group_header_color(accent)

    def _apply_audio_playlist_theme(self) -> None:
        """Keep the current-track brush aligned with the active JSON theme."""
        self.audio_panel.set_playlist_theme(
            active_background=str(self.theme_manager.current_value("colors", "accent")),
            text=str(self.theme_manager.current_value("colors", "text_primary")),
            active_text=str(self.theme_manager.current_value("colors", "text_on_accent")),
        )

    def _connect_signals(self) -> None:
        self.subtitle_panel.preview_requested.connect(
            lambda content: self.set_preview(ChannelRole.BROADCAST, content, True)
        )
        self.subtitle_panel.take_requested.connect(lambda: self.take(ChannelRole.BROADCAST))
        self.subtitle_panel.style_requested.connect(
            lambda: self.open_source_style_settings("praise")
        )
        self.subtitle_panel.status_changed.connect(self.status.setText)
        self.subtitle_panel.settings_changed.connect(self._praise_settings_changed)
        self.bible_panel.preview_requested.connect(
            lambda content: self.set_preview(ChannelRole.BROADCAST, content, True)
        )
        self.bible_panel.take_requested.connect(lambda: self.take(ChannelRole.BROADCAST))
        self.bible_panel.style_requested.connect(lambda: self.open_source_style_settings("bible"))
        self.bible_panel.reference_style_requested.connect(
            lambda: self.open_source_style_settings("bible_reference")
        )
        self.bible_panel.status_changed.connect(self.status.setText)
        self.bible_panel.bible_file_changed.connect(self._bible_file_changed)
        self.bible_panel.plan_file_changed.connect(self._bible_plan_file_changed)
        self.instant_panel.preview_requested.connect(
            lambda content: self.set_preview(ChannelRole.BROADCAST, content, True)
        )
        self.instant_panel.take_requested.connect(lambda: self.take(ChannelRole.BROADCAST))
        self.instant_panel.style_requested.connect(self.open_source_style_settings)
        self.instant_panel.status_changed.connect(self.status.setText)
        self.pdf_panel.preview_requested.connect(self.set_preview)
        self.pdf_panel.preview_ready.connect(self.mark_preview_ready)
        self.pdf_panel.send_to_both_requested.connect(self.send_to_both)
        self.pdf_panel.take_requested.connect(self.take)
        self.pdf_panel.take_both_requested.connect(self.take_both)
        self.pdf_panel.link_mode_changed.connect(self._pdf_link_mode_changed)
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
        self.video_panel.status_changed.connect(self.status.setText)
        self.audio_panel.folder_changed.connect(self._audio_folder_changed)
        self.audio_panel.settings_changed.connect(self._media_settings_changed)
        self.audio_panel.status_changed.connect(self.status.setText)
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
        self.coordinator.rendered.connect(self._preview_preset_pdf_rendered)
        self.screen_service.screens_changed.connect(self._screens_changed)
        self.sync_content_check.toggled.connect(self._linked_navigation_toggled)
        self.sync_auto_take_check.toggled.connect(self._linked_auto_take_toggled)
        self.sync_chroma_check.toggled.connect(self._broadcast_chroma_toggled)
        self.sync_previous_button.clicked.connect(lambda: self.move_linked_previews(-1))
        self.sync_next_button.clicked.connect(lambda: self.move_linked_previews(1))
        self.sync_take_button.clicked.connect(self.take_linked_previews)
        self.preview_preset_panel.save_requested.connect(self.save_preview_preset)
        self.preview_preset_panel.apply_requested.connect(self.apply_preview_preset)
        self.preview_preset_panel.rename_requested.connect(self.rename_preview_preset)
        self.preview_preset_panel.update_requested.connect(self.update_preview_preset)
        self.preview_preset_panel.delete_requested.connect(self.delete_preview_preset)
        self.preview_preset_panel.move_requested.connect(self.move_preview_preset)
        self.preview_preset_panel.open_file_requested.connect(self.choose_preview_preset_file)
        self.preview_preset_panel.save_file_as_requested.connect(self.save_preview_preset_file_as)
        self._linked_navigation_toggled(self.sync_content_check.isChecked())
        self._linked_auto_take_toggled(self.sync_auto_take_check.isChecked())

    def _restore_content(self) -> None:
        last_praise_plan = (
            Path(self.settings.last_praise_plan_file)
            if self.settings.last_praise_plan_file
            else None
        )
        if last_praise_plan and last_praise_plan.is_file():
            self.subtitle_panel.load_plan_path(last_praise_plan, warn=False)
        last_bible_plan = (
            Path(self.settings.last_bible_plan_file) if self.settings.last_bible_plan_file else None
        )
        if last_bible_plan and last_bible_plan.is_file():
            self.bible_panel.load_plan_path(last_bible_plan)

    def _restore_panel_layout(self) -> None:
        restored_stable_tab = False
        if self.settings.panel_layout.startswith("tab:"):
            source_id = self.settings.panel_layout.removeprefix("tab:")
            if source_id in {"instant", "black"}:
                source_id = "misc"
            for index in range(self.tabs.count()):
                tab_widget = self.tabs.widget(index)
                if (
                    tab_widget is not None
                    and tab_widget.objectName() == f"ContentSource_{source_id}"
                ):
                    self.tabs.setCurrentIndex(index)
                    restored_stable_tab = True
                    break
        try:
            prefix, index_text = self.settings.panel_layout.split(":", maxsplit=1)
            index = int(index_text)
        except (ValueError, AttributeError):
            prefix = ""
            index = -1
        if not restored_stable_tab and prefix == "tabs" and index >= 0:
            # Legacy tab 0 was the old subtitle panel, now Praise.
            mapped = 1 if index == 0 else index + 2
            if 0 <= mapped < self.tabs.count():
                self.tabs.setCurrentIndex(mapped)
        if self.settings.workspace_splitter_state:
            try:
                restored = self.workspace_splitter.restoreState(
                    QByteArray.fromBase64(self.settings.workspace_splitter_state.encode("ascii"))
                )
            except (ValueError, UnicodeError):
                restored = False
            self._workspace_splitter_state_restored = restored
        if not self._workspace_splitter_state_restored:
            QTimer.singleShot(0, self._apply_default_workspace_split)
        self._enforce_preview_preset_dock_visible()

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
            self.status.setText(f"{channel_label(role)} Preview 준비 중 · 기존 Live 유지")
        self._refresh_channel(role)
        if (
            self._linked_auto_take_pending
            and self._linked_auto_take_snapshot is not None
            and (
                self.state.broadcast.preview_content,
                self.state.venue.preview_content,
            )
            != self._linked_auto_take_snapshot
        ):
            self._cancel_linked_auto_take()

    def mark_preview_ready(
        self,
        role: ChannelRole | str,
        ready: bool,
        error: str,
    ) -> None:
        role = self._normalize_role(role)
        self.state.mark_preview_ready(role, ready, error)
        self.status.setText(
            f"{channel_label(role)} Preview 준비 완료"
            if ready
            else f"{channel_label(role)} Preview 오류: {error}"
        )
        self._refresh_channel(role)
        if self._linked_auto_take_pending:
            if not ready:
                self._cancel_linked_auto_take(
                    f"바로 Live 취소 · {channel_label(role)} Preview 오류: {error}"
                )
            else:
                self._try_linked_auto_take()

    def save_preview_preset(self, name: str) -> bool:
        """Save or overwrite the current two-channel Preview snapshot."""
        if any(
            content.subtitle_source.startswith("instant")
            for content in (
                self.state.broadcast.preview_content,
                self.state.venue.preview_content,
            )
        ):
            self.status.setText("즉석 콘텐츠는 예배 순서에 저장할 수 없습니다.")
            return False
        try:
            preset = PreviewPreset(
                name=name,
                broadcast_content=(self.state.broadcast.preview_content.as_preset_reference()),
                venue_content=self.state.venue.preview_content.as_preset_reference(),
            )
        except ValueError as error:
            self.status.setText(f"프리셋 저장 실패: {error}")
            return False
        proposed = list(self.preview_presets)
        existing = next(
            (
                index
                for index, candidate in enumerate(proposed)
                if candidate.name.casefold() == preset.name.casefold()
            ),
            None,
        )
        if existing is None:
            proposed.append(preset)
            action = "저장"
        else:
            proposed[existing] = preset
            action = "덮어쓰기"
        if not self._commit_preview_presets(
            proposed,
            f"'{preset.name}' Preview 프리셋 {action} 완료",
        ):
            return False
        self.preview_preset_panel.mark_saved()
        return True

    def apply_preview_preset(self, name: str) -> bool:
        """Prepare both channels from a preset without changing either Live output."""
        preset = self._preview_preset(name)
        if preset is None:
            self.status.setText(f"프리셋 적용 실패: '{name}'을 찾을 수 없습니다.")
            return False
        contents, error = self._resolve_preview_preset(preset)
        if error:
            self.status.setText(f"프리셋 적용 실패 · 기존 Preview 유지: {error}")
            return False
        assert contents is not None
        subtitle_position = next(
            (
                content.subtitle_card_index
                for content in contents.values()
                if content.kind is ContentType.SUBTITLE_KEY
            ),
            None,
        )
        if subtitle_position is not None:
            subtitle_content = next(
                content for content in contents.values() if content.kind is ContentType.SUBTITLE_KEY
            )
            if subtitle_content.subtitle_source == "bible":
                self.bible_panel.navigate(subtitle_position)
            else:
                self.subtitle_panel.set_preview_position(subtitle_position)
        pdf_position = next(
            (
                content.pdf_page
                for content in contents.values()
                if content.kind is ContentType.PDF_PAGE
            ),
            None,
        )
        if pdf_position is not None:
            pdf_content = next(
                content for content in contents.values() if content.kind is ContentType.PDF_PAGE
            )
            if (
                pdf_content.pdf_path is not None
                and self.pdf_panel.current_path is not None
                and pdf_content.pdf_path.resolve() == self.pdf_panel.current_path.resolve()
            ):
                self.pdf_panel.set_preview_position(pdf_position)
        for role, content in contents.items():
            old_request = self._preview_preset_pdf_requests.pop(role, None)
            if old_request is not None:
                self.coordinator.cancel(old_request)
            ready = content.kind not in {ContentType.PDF_PAGE, ContentType.VIDEO}
            self.set_preview(role, content, ready)

        video_roles = [
            role for role, content in contents.items() if content.kind is ContentType.VIDEO
        ]
        if len(video_roles) == 2 and (
            contents[ChannelRole.BROADCAST].video_source
            == contents[ChannelRole.VENUE].video_source
        ):
            video_source = contents[ChannelRole.BROADCAST].video_source
            assert video_source is not None
            self.video_manager.cue_both(video_source)
        else:
            for role in video_roles:
                video_source = contents[role].video_source
                assert video_source is not None
                self.video_manager.cue_preview(role, video_source)

        preparing_pdf = False
        for role, content in contents.items():
            if content.kind is not ContentType.PDF_PAGE:
                continue
            assert content.pdf_path is not None and content.pdf_page is not None
            token = ("order-preset", uuid4().hex, role)
            self._preview_preset_pdf_requests[role] = token
            self.coordinator.request(
                content.pdf_path,
                content.pdf_page,
                self._pdf_prepare_sizes()[role],
                token,
                priority=3,
            )
            preparing_pdf = True
        self.preview_preset_panel.mark_applied(name)
        self._focus_linked_controls()
        if preparing_pdf or video_roles:
            self.status.setText(f"'{name}' Preview 준비 중 · 완료 후 중앙 TAKE BOTH를 누르십시오.")
        else:
            self.status.setText(
                f"'{name}' Preview 적용 완료 · 확인 후 중앙 TAKE BOTH를 누르십시오."
            )
        return True

    def choose_preview_preset_file(self) -> bool:
        """Choose and load a worship-order JSON document."""
        start = (
            str(self.preview_preset_file.parent)
            if self.preview_preset_file is not None
            else str(Path.home())
        )
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "예배 순서 파일 열기",
            start,
            "Church Presenter 예배 순서 (*.json);;JSON 파일 (*.json)",
        )
        return bool(selected) and self.load_preview_preset_file(Path(selected))

    def load_preview_preset_file(self, path: Path) -> bool:
        """Replace the active list with a user-selected worship-order file."""
        try:
            presets = self.settings_service.load_preview_preset_file(path)
            self.settings_service.save_preview_presets(presets)
        except (OSError, UnicodeError, KeyError, ValueError, TypeError) as error:
            LOGGER.exception("Could not load worship-order file %s", path)
            self.status.setText(f"예배 순서 파일 열기 실패 · 기존 목록 유지: {error}")
            return False
        self.preview_presets = presets
        self.preview_preset_file = path.expanduser().resolve()
        self.settings.preview_preset_file = str(self.preview_preset_file)
        self.preview_preset_panel.applied_name = ""
        self.preview_preset_panel.set_presets(presets)
        self.preview_preset_panel.set_file_path(str(self.preview_preset_file))
        try:
            self.settings_service.save(self.settings)
        except OSError:
            LOGGER.exception("Could not remember worship-order file %s", path)
            self.status.setText("예배 순서 파일은 열었지만 마지막 파일 설정은 저장하지 못했습니다.")
            return True
        self.status.setText(
            f"예배 순서 파일 기준으로 목록을 초기화했습니다: "
            f"{self.preview_preset_file.name} · Preview/Live 유지"
        )
        return True

    def save_preview_preset_file(self, path: Path | None = None) -> bool:
        """Save the active worship order, prompting for a path when necessary."""
        target = path or self.preview_preset_file
        if target is None:
            return self.save_preview_preset_file_as()
        target = target.expanduser()
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        try:
            self.settings_service.save_preview_preset_file(
                target,
                self.preview_presets,
            )
        except (OSError, ValueError, TypeError) as error:
            LOGGER.exception("Could not save worship-order file %s", target)
            self.status.setText(f"예배 순서 파일 저장 실패: {error}")
            return False
        self.preview_preset_file = target.resolve()
        self.settings.preview_preset_file = str(self.preview_preset_file)
        self.preview_preset_panel.set_file_path(str(self.preview_preset_file))
        try:
            self.settings_service.save(self.settings)
        except OSError:
            LOGGER.exception("Could not remember worship-order file %s", target)
            self.status.setText(
                "예배 순서 파일은 저장했지만 마지막 파일 설정은 저장하지 못했습니다."
            )
            return True
        self.status.setText(f"예배 순서 파일 저장 완료: {self.preview_preset_file.name}")
        return True

    def save_preview_preset_file_as(self) -> bool:
        """Choose a new path and save the active worship order."""
        suggested = (
            str(self.preview_preset_file.with_name(f"{self.preview_preset_file.stem}_수정본.json"))
            if self.preview_preset_file is not None
            else str(Path.home() / "예배_순서.json")
        )
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "예배 순서 다른 이름으로 저장",
            suggested,
            "Church Presenter 예배 순서 (*.json);;JSON 파일 (*.json)",
        )
        return bool(selected) and self.save_preview_preset_file(Path(selected))

    def rename_preview_preset(self, old_name: str, new_name: str) -> bool:
        """Rename a worship-order preset without changing its position."""
        preset = self._preview_preset(old_name)
        if preset is None:
            return False
        if any(
            candidate.name.casefold() == new_name.strip().casefold() and candidate.name != old_name
            for candidate in self.preview_presets
        ):
            self.status.setText("프리셋 이름 변경 실패: 같은 이름이 이미 있습니다.")
            return False
        try:
            renamed = PreviewPreset(
                new_name,
                preset.broadcast_content,
                preset.venue_content,
            )
        except ValueError as error:
            self.status.setText(f"프리셋 이름 변경 실패: {error}")
            return False
        proposed = [renamed if item.name == old_name else item for item in self.preview_presets]
        return self._commit_preview_presets(
            proposed,
            f"프리셋 이름을 '{renamed.name}'(으)로 변경했습니다.",
        )

    def update_preview_preset(self, name: str) -> bool:
        """Overwrite one named cue with the current two-channel Preview positions."""
        index = next(
            (
                candidate_index
                for candidate_index, preset in enumerate(self.preview_presets)
                if preset.name == name
            ),
            -1,
        )
        if index < 0:
            self.status.setText(f"프리셋 수정 실패: '{name}'을 찾을 수 없습니다.")
            return False
        try:
            updated = PreviewPreset(
                name,
                self.state.broadcast.preview_content.as_preset_reference(),
                self.state.venue.preview_content.as_preset_reference(),
            )
        except ValueError as error:
            self.status.setText(f"프리셋 수정 실패: {error}")
            return False
        proposed = list(self.preview_presets)
        proposed[index] = updated
        self.preview_presets = proposed
        self.preview_preset_panel.set_presets(proposed)
        self.preview_preset_panel.mark_applied(name)
        self.status.setText(
            f"'{name}' 항목을 현재 Preview 위치로 임시 수정했습니다. "
            "JSON으로 남기려면 다른 이름을 누르십시오."
        )
        return True

    def delete_preview_preset(self, name: str) -> bool:
        """Delete one named Preview preset."""
        proposed = [preset for preset in self.preview_presets if preset.name != name]
        if len(proposed) == len(self.preview_presets):
            return False
        return self._commit_preview_presets(proposed, f"'{name}' 프리셋을 삭제했습니다.")

    def move_preview_preset(self, name: str, offset: int) -> bool:
        """Move a preset one position in the worship order."""
        index = next(
            (i for i, preset in enumerate(self.preview_presets) if preset.name == name),
            -1,
        )
        destination = index + offset
        if index < 0 or not 0 <= destination < len(self.preview_presets):
            return False
        proposed = list(self.preview_presets)
        proposed[index], proposed[destination] = proposed[destination], proposed[index]
        return self._commit_preview_presets(proposed, "예배 순서 프리셋 순서를 변경했습니다.")

    def _commit_preview_presets(
        self,
        proposed: list[PreviewPreset],
        success_message: str,
    ) -> bool:
        try:
            self.settings_service.save_preview_presets(proposed)
        except (OSError, ValueError, TypeError) as error:
            LOGGER.exception("Could not save Preview presets")
            self.status.setText(f"프리셋 저장 실패: {error}")
            return False
        self.preview_presets = proposed
        self.preview_preset_panel.set_presets(proposed)
        self.status.setText(success_message)
        return True

    def _preview_preset(self, name: str) -> PreviewPreset | None:
        return next((preset for preset in self.preview_presets if preset.name == name), None)

    def _resolve_preview_preset(
        self,
        preset: PreviewPreset,
    ) -> tuple[dict[ChannelRole, Content] | None, str]:
        """Resolve saved sources, falling back to the active source when unavailable."""
        resolved: dict[ChannelRole, Content] = {}
        cue_rows = (
            (ChannelRole.BROADCAST, preset.broadcast_content),
            (ChannelRole.VENUE, preset.venue_content),
        )
        # A subtitle plan load changes panel navigation state. Validate the other
        # channel's file/page first so a later PDF/video error cannot partially
        # apply the preset to either Preview.
        ordered_rows = sorted(
            cue_rows,
            key=lambda row: row[1].kind is ContentType.SUBTITLE_KEY,
        )
        for role, cue in ordered_rows:
            label = channel_label(role)
            if cue.kind is ContentType.BLACK:
                resolved[role] = Content.black()
                continue
            if cue.kind is ContentType.SOLID_COLOR:
                resolved[role] = Content.solid_color(cue.background_color)
                continue
            if cue.kind is ContentType.SUBTITLE_KEY:
                position = cue.subtitle_card_index
                if cue.subtitle_source == "bible":
                    plan_path = self._available_source_path(
                        cue.subtitle_path,
                        self.bible_panel.plan_path,
                    )
                    if plan_path is not None and (
                        self.bible_panel.plan_path is None
                        or self.bible_panel.plan_path.resolve() != plan_path
                    ) and not self.bible_panel.load_plan_path(plan_path):
                        return None, f"{label} 성경 콘티를 열 수 없습니다."
                    try:
                        resolved[role] = self.bible_panel.content_for_reference(
                            cue.subtitle_reference
                        )
                    except (KeyError, ValueError) as error:
                        return None, f"{label} 성경 구절을 확인할 수 없습니다: {error}"
                    continue
                if cue.subtitle_source == "praise" and cue.subtitle_reference:
                    plan_path = self._available_source_path(
                        cue.subtitle_path,
                        self.subtitle_panel.plan_path,
                    )
                    if plan_path is not None and (
                        self.subtitle_panel.plan_path is None
                        or self.subtitle_panel.plan_path.resolve() != plan_path
                    ) and not self.subtitle_panel.load_plan_path(plan_path, warn=False):
                        return None, f"{label} 찬양 콘티를 열 수 없습니다."
                    try:
                        resolved[role] = self.subtitle_panel.content_for_reference(
                            cue.subtitle_reference
                        )
                    except (KeyError, ValueError) as error:
                        return None, f"{label} 찬양 카드를 확인할 수 없습니다: {error}"
                    continue
                if position is None or not 0 <= position < self.subtitle_panel.output_count:
                    return None, (
                        f"{label} 자막 카드 {self._display_position(position)}가 "
                        "현재 찬양 콘티에 없습니다."
                    )
                resolved[role] = self.subtitle_panel._content_at(position)
                continue
            if cue.kind is ContentType.PDF_PAGE:
                position = cue.pdf_page
                path = self._available_source_path(cue.pdf_path, self.pdf_panel.current_path)
                if path is None:
                    return None, f"{label}에 사용할 PDF를 먼저 선택하십시오."
                try:
                    page_count = pdf_page_count(path)
                except Exception as error:
                    return None, f"{label} PDF를 열 수 없습니다: {error}"
                if position is None or not 0 <= position < page_count:
                    return None, (
                        f"{label} PDF {self._display_position(position)}쪽이 선택한 PDF에 없습니다."
                    )
                resolved[role] = Content.pdf(path, position)
                continue
            if cue.kind is ContentType.VIDEO:
                source: Path | str | None
                if cue.video_url:
                    source = cue.video_url
                else:
                    active_source = self.video_panel.selected_source
                    if cue.video_path is not None and cue.video_path.is_file():
                        source = cue.video_path
                    elif isinstance(active_source, str) or (
                        active_source is not None and active_source.is_file()
                    ):
                        source = active_source
                    else:
                        source = None
                if source is None or (isinstance(source, Path) and not source.is_file()):
                    return None, f"{label}에 사용할 영상을 먼저 선택하십시오."
                resolved[role] = (
                    Content.youtube_video(source)
                    if isinstance(source, str)
                    else Content.video(source)
                )
                continue
            return None, f"{label} 콘텐츠 종류를 지원하지 않습니다: {cue.kind.value}"
        return resolved, ""

    @staticmethod
    def _available_source_path(
        saved_path: Path | None,
        active_path: Path | None,
    ) -> Path | None:
        """Prefer an existing saved path, then an existing active path."""
        if saved_path is not None:
            resolved = saved_path.expanduser().resolve()
            if resolved.is_file():
                return resolved
        if active_path is not None:
            resolved = active_path.expanduser().resolve()
            if resolved.is_file():
                return resolved
        return None

    @staticmethod
    def _display_position(position: int | None) -> str:
        return "미지정" if position is None else str(position + 1)

    def _preview_preset_pdf_rendered(
        self,
        _key: object,
        _image: QImage,
        error: str,
        token: object,
    ) -> None:
        if not (
            isinstance(token, tuple)
            and len(token) == 3
            and token[0] == "order-preset"
            and isinstance(token[2], ChannelRole)
        ):
            return
        role = token[2]
        if self._preview_preset_pdf_requests.get(role) != token:
            return
        del self._preview_preset_pdf_requests[role]
        self.mark_preview_ready(role, not error, error)
        if not self._preview_preset_pdf_requests and not error:
            self.status.setText("프리셋 Preview 준비 완료 · 중앙 TAKE BOTH 가능")

    def send_to_both(self, content: Content, ready: bool) -> None:
        if content.kind is ContentType.SUBTITLE_KEY:
            self.status.setText("자막은 송출 전용입니다.")
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
            self.state.channel(role).preview_content.kind is not ContentType.VIDEO for role in roles
        ):
            for role in roles:
                if self.state.channel(role).preview_content.kind is not ContentType.VIDEO:
                    self.video_panel.invalidate_preview(role)
            self.status.setText("TAKE BOTH 실패 · 양쪽 Preview가 모두 영상이어야 합니다.")
            return False
        return self.take_both()

    def take(self, role: ChannelRole | str) -> bool:
        self._cancel_linked_auto_take()
        role = self._normalize_role(role)
        next_content = self.state.channel(role).preview_content
        previous_live = self.state.channel(role).live_content
        if next_content.kind is ContentType.VIDEO and (
            next_content.video_source is None
            or not self.video_manager.can_activate(role, next_content.video_source)
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
            assert next_content.video_source is not None
            if not self.video_manager.activate_preview(role, next_content.video_source):
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
            self._mark_subtitle_live(self.state.broadcast.live_content)
        if self.state.channel(role).live_content.kind is ContentType.PDF_PAGE:
            self.pdf_panel.mark_live(
                role,
                self.state.channel(role).live_content.pdf_page,
            )
        self._push_live(role)
        self._refresh_channel(role)
        self.status.setText(f"{channel_label(role)} TAKE 완료")
        return True

    def take_both(self) -> bool:
        self._cancel_linked_auto_take()
        previous = {
            ChannelRole.BROADCAST: self.state.broadcast.live_content,
            ChannelRole.VENUE: self.state.venue.live_content,
        }
        for role in (ChannelRole.BROADCAST, ChannelRole.VENUE):
            content = self.state.channel(role).preview_content
            if content.kind is ContentType.VIDEO and (
                content.video_source is None
                or not self.video_manager.can_activate(role, content.video_source)
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
                assert content.video_source is not None
                if not self.video_manager.activate_preview(role, content.video_source):
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
            self._mark_subtitle_live(self.state.broadcast.live_content)
        if self.state.broadcast.live_content.kind is ContentType.PDF_PAGE:
            self.pdf_panel.mark_live(
                ChannelRole.BROADCAST,
                self.state.broadcast.live_content.pdf_page,
            )
        if self.state.venue.live_content.kind is ContentType.PDF_PAGE:
            self.pdf_panel.mark_live(
                ChannelRole.VENUE,
                self.state.venue.live_content.pdf_page,
            )
        self._refresh_all()
        self.status.setText(
            "TAKE BOTH 완료 · 영상 Play/Pause/Stop 양쪽 연동"
            if video_transport_linked
            else "TAKE BOTH 원자적 전환 완료"
        )
        return True

    def _linked_navigation_toggled(self, enabled: bool) -> None:
        self.settings.subtitle_pdf_linked = enabled
        self.sync_content_check.setText("동시 진행")
        if enabled:
            self.settings.pdf_link_outputs = False
            if self.pdf_panel.link_outputs:
                self.pdf_panel.set_link_outputs(False)
            self.status.setText(
                "동시 진행 영역에 포커스를 두면 방향키로 각 Preview 콘텐츠를 함께 준비합니다."
            )
        else:
            self._cancel_linked_auto_take()

    def _linked_auto_take_toggled(self, enabled: bool) -> None:
        self.settings.linked_navigation_auto_take = enabled
        if not enabled:
            self._cancel_linked_auto_take()
            return
        self.status.setText(
            "바로 Live 활성화 · Left/Right 또는 PageUp/PageDown 입력 후 "
            "준비가 끝나면 TAKE BOTH를 자동 실행합니다."
        )

    def _effective_live_content(self, role: ChannelRole) -> Content:
        if role is ChannelRole.BROADCAST and self.sync_chroma_check.isChecked():
            return BROADCAST_CHROMA_CONTENT
        return self.state.channel(role).live_content

    def _broadcast_chroma_toggled(self, enabled: bool) -> None:
        self._push_live(ChannelRole.BROADCAST)
        self.status.setText(
            "송출 화면을 크로마키 그린으로 전환했습니다."
            if enabled
            else "크로마키 해제 · 최신 송출 Live를 복원했습니다."
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
            self._move_active_subtitle(offset)
        if pdf_roles:
            self.pdf_panel.move_preview_for_roles(offset, pdf_roles)
        if not subtitle_active and not pdf_roles:
            self._cancel_linked_auto_take()
            self.status.setText("함께 이동할 자막 또는 PDF가 송출/현장 Preview에 없습니다.")
            return
        self._show_linked_position()
        self._queue_linked_auto_take()

    def first_linked_previews(self) -> None:
        if not self.sync_content_check.isChecked():
            self.sync_content_check.setChecked(True)
        subtitle_active, pdf_roles = self._linked_preview_targets()
        if subtitle_active:
            self._navigate_active_subtitle(first=True)
        if pdf_roles:
            self.pdf_panel.navigate_first_for_roles(pdf_roles)
        self._show_linked_position()

    def last_linked_previews(self) -> None:
        if not self.sync_content_check.isChecked():
            self.sync_content_check.setChecked(True)
        subtitle_active, pdf_roles = self._linked_preview_targets()
        if subtitle_active:
            self._navigate_active_subtitle(first=False)
        if pdf_roles:
            self.pdf_panel.navigate_last_for_roles(pdf_roles)
        self._show_linked_position()

    def take_linked_previews(self) -> bool:
        if not self.sync_content_check.isChecked():
            self.sync_content_check.setChecked(True)
        return self.take_both()

    def _queue_linked_auto_take(self) -> None:
        if not self.sync_auto_take_check.isChecked():
            self._cancel_linked_auto_take()
            return
        self._linked_auto_take_pending = True
        self._linked_auto_take_snapshot = (
            self.state.broadcast.preview_content,
            self.state.venue.preview_content,
        )
        self._try_linked_auto_take()

    def _try_linked_auto_take(self) -> None:
        if not self._linked_auto_take_pending:
            return
        snapshot = self._linked_auto_take_snapshot
        current = (
            self.state.broadcast.preview_content,
            self.state.venue.preview_content,
        )
        if (
            not self.sync_auto_take_check.isChecked()
            or not self.sync_content_check.isChecked()
            or snapshot is None
            or current != snapshot
        ):
            self._cancel_linked_auto_take()
            return
        if not self.state.broadcast.is_ready or not self.state.venue.is_ready:
            self.status.setText("바로 Live 대기 · 두 Preview를 준비하고 있습니다.")
            return
        self._linked_auto_take_pending = False
        self._linked_auto_take_snapshot = None
        self.take_both()

    def _cancel_linked_auto_take(self, message: str = "") -> None:
        was_pending = self._linked_auto_take_pending
        self._linked_auto_take_pending = False
        self._linked_auto_take_snapshot = None
        if message and was_pending:
            self.status.setText(message)

    def _linked_preview_targets(self) -> tuple[bool, tuple[ChannelRole, ...]]:
        subtitle_active = self.state.broadcast.preview_content.kind is ContentType.SUBTITLE_KEY
        pdf_roles = tuple(
            role
            for role in (ChannelRole.BROADCAST, ChannelRole.VENUE)
            if self.state.channel(role).preview_content.kind is ContentType.PDF_PAGE
        )
        return subtitle_active, pdf_roles

    def _show_linked_position(self) -> None:
        source = self.state.broadcast.preview_content.subtitle_source
        if source == "bible":
            subtitle_count = self.bible_panel.output_count
            subtitle_index = self.bible_panel.preview_index
        elif source == "instant_text":
            subtitle_count = self.instant_panel.output_count
            subtitle_index = self.instant_panel.preview_index
        else:
            subtitle_count = self.subtitle_panel.output_count
            subtitle_index = self.subtitle_panel.preview_index
        subtitle_position = str(subtitle_index + 1) if subtitle_count else "없음"
        pdf_position = (
            str(self.pdf_panel.preview_position + 1) if self.pdf_panel.page_order else "없음"
        )
        self.status.setText(
            f"함께 이동 · 자막 {subtitle_position}/{subtitle_count or '-'} · "
            f"PDF 순서 {pdf_position}/{len(self.pdf_panel.page_order) or '-'}"
        )

    def _move_active_subtitle(self, offset: int) -> None:
        source = self.state.broadcast.preview_content.subtitle_source
        if source == "bible":
            self.bible_panel.move_preview(offset)
        elif source == "instant_text":
            self.instant_panel.move_preview(offset)
        elif not source.startswith("instant"):
            self.subtitle_panel.move_preview(offset)

    def _navigate_active_subtitle(self, *, first: bool) -> None:
        source = self.state.broadcast.preview_content.subtitle_source
        if source == "bible":
            target = 0 if first else self.bible_panel.output_count - 1
            self.bible_panel.navigate(target)
        elif source == "instant_text":
            target = 0 if first else self.instant_panel.output_count - 1
            self.instant_panel.navigate(target)
        elif not source.startswith("instant"):
            target = 0 if first else self.subtitle_panel.output_count - 1
            self.subtitle_panel.navigate(target)

    def open_style_settings(self) -> None:
        self.open_source_style_settings("praise")

    def open_source_style_settings(self, source: str) -> None:
        style_source = source
        from_instant = self.tabs.currentWidget() is self.misc_panel
        style = {
            "instant_text": self.instant_text_style,
            "praise": self.praise_style,
            "bible": self.bible_style,
            "bible_reference": self.bible_reference_style,
        }[style_source]
        key_color = {
            "instant_text": self.settings.instant_text_key_color,
            "praise": self.settings.praise_key_color,
            "bible": self.settings.bible_key_color,
            "bible_reference": self.settings.bible_key_color,
        }[style_source]
        dialog = SubtitleStyleDialog(
            self.settings_service,
            self.coordinator,
            style,
            key_color,
            self.settings.current_style_preset,
            (
                self.subtitle_panel.group_size
                if style_source == "praise"
                else self.bible_panel.group_size
                if style_source == "bible"
                else self.instant_panel.group_size
                if style_source == "instant_text"
                else 1
            ),
            self,
            preview_text="요한복음 3:16" if style_source == "bible_reference" else None,
            reference_mode=style_source == "bible_reference",
            group_label=(
                "한 번에 표시할 절 수"
                if style_source == "bible"
                else "한 번에 표시할 자막 수"
            ),
            body_style=self.bible_style if style_source == "bible_reference" else None,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if style_source == "instant_text":
            self.instant_text_style = dialog.result_style
            self.settings.instant_text_style = dialog.result_style.to_dict()
            self.settings.instant_text_key_color = dialog.result_key_color
            self.settings.instant_text_group_size = dialog.result_group_size
            self.instant_panel.set_group_size(dialog.result_group_size)
        elif style_source == "praise":
            self.praise_style = dialog.result_style
            self.settings.praise_style = dialog.result_style.to_dict()
            self.settings.praise_key_color = dialog.result_key_color
            self.settings.key_color = dialog.result_key_color
            self.subtitle_panel.set_group_size(dialog.result_group_size)
            self.subtitle_panel.set_style(
                dialog.result_style,
                dialog.result_key_color,
                refresh_preview=not from_instant,
            )
        elif style_source == "bible":
            self.bible_style = dialog.result_style
            self.settings.bible_style = dialog.result_style.to_dict()
            self.settings.bible_key_color = dialog.result_key_color
            self.settings.bible_group_size = dialog.result_group_size
            self.bible_panel.set_group_size(
                dialog.result_group_size,
                refresh_preview=not from_instant,
            )
            self.bible_panel.set_style(
                dialog.result_style,
                dialog.result_key_color,
                refresh_preview=not from_instant,
            )
        else:
            self.bible_reference_style = dialog.result_style
            self.settings.bible_reference_style = dialog.result_style.to_dict()
            self.settings.bible_key_color = dialog.result_key_color
            self.bible_panel.set_reference_style(
                dialog.result_style,
                dialog.result_key_color,
                refresh_preview=not from_instant,
            )
        if style_source == "instant_text":
            self.instant_panel.set_style(dialog.result_style, dialog.result_key_color)
        if from_instant and self.state.broadcast.preview_content.subtitle_source == "instant_text":
            self.instant_panel.preview_current()
        self.settings.current_style_preset = dialog.result_preset
        self.status.setText(
            "자막 스타일을 송출 Preview에 적용했습니다. Live는 변경되지 않았습니다."
        )

    def _mark_subtitle_live(self, content: Content) -> None:
        if content.subtitle_source == "bible":
            self.bible_panel.mark_live()
        elif content.subtitle_source.startswith("instant"):
            self.instant_panel.mark_live(content.subtitle_source)
        else:
            self.subtitle_panel.mark_live()

    def _bible_file_changed(self, path: str) -> None:
        self.settings.bible_file = path
        self.bible_path = Path(path)
        self.bible_repository = self.bible_panel.repository

    def _bible_plan_file_changed(self, path: str) -> None:
        self.settings.last_bible_plan_file = path

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
        self.resize(
            min(self.width(), available.width()),
            min(self.height(), available.height()),
        )
        x = available.x() + max(0, (available.width() - self.width()) // 2)
        y = available.y() + max(0, (available.height() - self.height()) // 2)
        self.move(x, y)

    def showEvent(self, event: QShowEvent) -> None:
        """Keep restored Controller geometry inside the usable screen area."""
        super().showEvent(event)
        screen = self.screen() or self.application.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.resize(
            min(self.width(), available.width()),
            min(self.height(), available.height()),
        )
        maximum_x = available.x() + available.width() - self.width()
        maximum_y = available.y() + available.height() - self.height()
        self.move(
            max(available.x(), min(self.x(), maximum_x)),
            max(available.y(), min(self.y(), maximum_y)),
        )
        self._apply_ui_density(self.size())
        QTimer.singleShot(0, self._apply_default_workspace_split)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep the main controls usable when the Controller becomes narrow."""
        super().resizeEvent(event)
        if hasattr(self, "header_layout"):
            self._update_header_layout(event.size().width())
        if hasattr(self, "workspace_splitter"):
            self._apply_ui_density(event.size())
        if hasattr(self, "pdf_panel"):
            self.pdf_panel.set_compact_actions(self._ui_density == "compact")
            QTimer.singleShot(0, self._fit_scroll_content)

    def _show_remote_connection(self) -> None:
        if self.remote_connection_dialog is None:
            self.remote_connection_dialog = RemoteConnectionDialog(
                self.remote_service,
                self,
            )
        self.remote_connection_dialog.open_connection()

    def _remote_state_changed(self, state: str, message: str) -> None:
        labels = {
            "starting": "원격 서버 시작 중",
            "waiting": "원격 연결 대기 중",
            "stopped": "원격 서버 중지됨",
            "no_address": "원격 연결 · 사용 가능한 로컬 IP 없음",
            "error": "원격 서버 오류",
        }
        if state in labels:
            self.status.setText(f"{labels[state]}{f' · {message}' if message else ''}")

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
                self.broadcast_simulator.set_content(
                    self._effective_live_content(ChannelRole.BROADCAST)
                )
                self.broadcast_simulator.show()
            else:
                self._disconnect_role(ChannelRole.BROADCAST, "가상 송출 화면 연결 해제")
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
                self._disconnect_role(ChannelRole.VENUE, "가상 현장 화면 연결 해제")
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
        self.broadcast_output.set_content(
            self._effective_live_content(ChannelRole.BROADCAST)
        )
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
                    self.broadcast_output if role is ChannelRole.BROADCAST else self.venue_output
                )
            return window is not None and window.isVisible()

        if all(is_active(role) for role in roles):
            return True
        if not self.start_outputs() or not all(is_active(role) for role in roles):
            labels = ", ".join(channel_label(role) for role in roles)
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
        content = self._effective_live_content(role)
        fade = FIXED_OUTPUT_FADE_DURATION_MS
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
            if path is not None:
                self._video_live_frame(role, str(path), frame)

    def _refresh_channel(self, role: ChannelRole) -> None:
        channel = self.state.channel(role)
        if role is ChannelRole.BROADCAST:
            self.broadcast_preview.set_content(channel.preview_content)
            self.broadcast_live.set_content(self._effective_live_content(role))
        else:
            self.venue_preview.set_content(channel.preview_content)
            self.venue_live.set_content(channel.live_content)
        self.sync_take_button.setEnabled(
            self.state.broadcast.is_ready and self.state.venue.is_ready
        )

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
            self._disconnect_role(ChannelRole.BROADCAST, "송출 화면이 분리되었습니다.")
        if self.venue_output is not None and self.settings.venue_screen_id not in ids:
            self._disconnect_role(ChannelRole.VENUE, "현장 화면이 분리되었습니다.")
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

    def _praise_settings_changed(
        self,
        group_size: int,
        plan_path: str,
        song_folder: str,
    ) -> None:
        self.settings.subtitle_group_size = group_size
        self.settings.last_praise_plan_file = plan_path
        self.settings.song_folder = song_folder

    def _pdf_folder_changed(self, folder: str) -> None:
        self.settings.pdf_folder = folder

    def _pdf_selection_changed(self, path: str, page: int) -> None:
        self.settings.last_pdf_file = path
        self.settings.last_pdf_page = page

    def _video_folder_changed(self, folder: str) -> None:
        self.settings.video_folder = folder

    def _audio_folder_changed(self, folder: str) -> None:
        self.settings.audio_folder = folder

    def _video_selection_changed(self, path: str) -> None:
        self.settings.last_video_file = "" if path.startswith(("http://", "https://")) else path

    def _media_settings_changed(self) -> None:
        self.settings.video_sort_field = self.video_panel.sort_field
        self.settings.video_sort_descending = self.video_panel.descending
        self.settings.audio_sort_field = self.audio_panel.sort_field
        self.settings.audio_sort_descending = self.audio_panel.descending
        self.settings.video_volume = self.video_panel.volume_slider.value()
        self.settings.video_muted = self.video_panel.mute_check.isChecked()
        self.settings.fade_duration_ms = FIXED_OUTPUT_FADE_DURATION_MS
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
            or content.video_source_key != path
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
        frame: object,
    ) -> None:
        role = self._normalize_role(role)
        surfaces = (
            (self.broadcast_live.surface,)
            if role is ChannelRole.BROADCAST
            else (self.venue_live.surface,)
        )
        for surface in surfaces:
            surface.set_video_frame(path, frame)
        if role is ChannelRole.BROADCAST:
            if self.broadcast_output:
                self.broadcast_output.surface.set_video_frame(path, frame)
            if self.broadcast_simulator:
                self.broadcast_simulator.surface.set_video_frame(path, frame)
        else:
            if self.venue_output:
                self.venue_output.surface.set_video_frame(path, frame)
            if self.venue_simulator:
                self.venue_simulator.surface.set_video_frame(path, frame)

    def _restore_live_video_frames(self) -> None:
        for role in (ChannelRole.BROADCAST, ChannelRole.VENUE):
            path, frame = self.video_manager.last_live_frame(role)
            if path is not None:
                self._video_live_frame(role, str(path), frame)

    def _video_play_started(self, role: ChannelRole | str) -> None:
        role = self._normalize_role(role)
        target = (
            "송출 + 현장 영상 재생"
            if self.video_manager.is_live_transport_linked
            else f"{channel_label(role)} 영상 재생"
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

    def _focus_linked_controls(self) -> None:
        """Hand keyboard control from a preset button to the linked control bar."""
        self.sync_next_button.setFocus(Qt.FocusReason.OtherFocusReason)
        self._focus_changed(None, self.sync_next_button)

    def _keyboard_area(self, focus: QWidget | None) -> str | None:
        if focus is None or (focus is not self and not self.isAncestorOf(focus)):
            return None
        if self._is_within(focus, self.sync_bar):
            return "linked"
        if self._is_within(focus, self.instant_panel):
            return "instant"
        if self._is_within(focus, self.bible_panel):
            return "bible"
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
            if panel is self.instant_panel:
                return "instant"
            if panel is self.bible_panel:
                return "bible"
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
        if isinstance(
            focus,
            (QLineEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox, QSlider),
        ):
            return False
        area = self._keyboard_area(focus)
        if area is None:
            return False
        if area != "linked" and isinstance(focus, QAbstractButton):
            return False
        key = event.key()
        if area == "linked":
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp):
                self.move_linked_previews(-1)
            elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown):
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
                self.subtitle_panel.navigate(self.subtitle_panel.output_count - 1)
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.take(ChannelRole.BROADCAST)
            else:
                return False
            return True
        if area == "bible":
            if key == Qt.Key.Key_Left:
                self.bible_panel.move_preview(-1)
            elif key == Qt.Key.Key_Right:
                self.bible_panel.move_preview(1)
            elif key == Qt.Key.Key_Home:
                self.bible_panel.navigate(0)
            elif key == Qt.Key.Key_End:
                self.bible_panel.navigate(self.bible_panel.output_count - 1)
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.take(ChannelRole.BROADCAST)
            else:
                return False
            return True
        if area == "instant":
            if key == Qt.Key.Key_Left:
                self.instant_panel.move_preview(-1)
            elif key == Qt.Key.Key_Right:
                self.instant_panel.move_preview(1)
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
        if not self._handle_navigation_key(event):
            super().keyPressEvent(event)

    def _persist_settings(self) -> None:
        self.settings.sort_field = self.pdf_panel.sort_field
        self.settings.sort_descending = self.pdf_panel.descending
        self._media_settings_changed()
        self.settings.audio_position_ms = self.audio_controller.runtime.position_ms
        current_audio = self.audio_controller.playlist.current_item
        self.settings.last_audio_file = (
            str(current_audio.path)
            if current_audio is not None and current_audio.path is not None
            else ""
        )
        current_panel = self.tabs.currentWidget()
        object_name = current_panel.objectName() if current_panel is not None else ""
        self.settings.panel_layout = (
            f"tab:{object_name.removeprefix('ContentSource_')}"
            if object_name.startswith("ContentSource_")
            else f"tabs:{self.tabs.currentIndex()}"
        )
        splitter_data = self.workspace_splitter.saveState().toBase64().data()
        self.settings.workspace_splitter_state = bytes(splitter_data).decode("ascii")
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
            chroma_signals_blocked = self.sync_chroma_check.blockSignals(True)
            self.sync_chroma_check.setChecked(False)
            self.sync_chroma_check.blockSignals(chroma_signals_blocked)
            self.state.black_all()
            self._refresh_all()
            self._push_live(ChannelRole.BROADCAST)
            self._push_live(ChannelRole.VENUE)
            self.application.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
            self.remote_input_dispatcher.enabled = False
            self.frame_capture.stop()
            self.remote_service.stop()
            self.video_manager.close()
            self.audio_controller.close()
            self.stop_outputs()
            self._persist_settings()
        except Exception:
            LOGGER.exception("Error during safe shutdown")
            self.stop_outputs()
        self.application.removeEventFilter(self)
        event.accept()
