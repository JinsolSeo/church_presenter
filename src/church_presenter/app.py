from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from church_presenter.logging_config import configure_logging
from church_presenter.services.screen_service import ScreenService
from church_presenter.services.settings_service import SettingsService
from church_presenter.ui.controller_window import ControllerWindow
from church_presenter.ui.styles import apply_application_style


def main() -> int:
    """Run one QApplication containing Controller and all outputs."""
    configure_logging()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    application = QApplication(sys.argv)
    application.setApplicationName("Church Presenter")
    application.setOrganizationName("JinsolSeo")
    apply_application_style(application)
    settings_service = SettingsService()
    result = settings_service.load()
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
        result.warning,
        previous_unclean,
    )
    controller.show()
    exit_code = application.exec()
    marker.unlink(missing_ok=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
