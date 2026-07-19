from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from church_presenter.logging_config import configure_logging
from church_presenter.services.screen_service import ScreenService
from church_presenter.services.settings_service import SettingsService
from church_presenter.ui.controller_window import ControllerWindow
from church_presenter.ui.styles import DEFAULT_THEME_ID, ThemeManager


def main() -> int:
    """Run one QApplication containing Controller and all outputs."""
    configure_logging()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    application = QApplication(sys.argv)
    application.setApplicationName("Church Presenter")
    application.setOrganizationName("JinsolSeo")
    settings_service = SettingsService()
    result = settings_service.load()
    theme_manager = ThemeManager()
    applied_theme = theme_manager.apply_theme(application, result.settings.current_theme)
    result.settings.current_theme = applied_theme or DEFAULT_THEME_ID
    startup_warning = " ".join(
        warning for warning in (result.warning, theme_manager.last_warning) if warning
    )
    marker = settings_service.config_dir / "session-active"
    previous_unclean = marker.exists()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("active\n", encoding="utf-8")
    screen_service = ScreenService(application)
    controller = ControllerWindow(
        application,
        screen_service,
        settings_service,
        result.settings,
        startup_warning,
        previous_unclean,
        theme_manager=theme_manager,
    )
    controller.show()
    exit_code = application.exec()
    marker.unlink(missing_ok=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
