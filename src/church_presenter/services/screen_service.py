from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication, QScreen

from church_presenter.domain.models import ScreenInfo


class ScreenService(QObject):
    """Qt screen discovery behind a testable abstraction."""

    screens_changed = Signal()

    def __init__(self, application: QGuiApplication) -> None:
        super().__init__()
        self.application = application
        application.screenAdded.connect(self._screen_added)
        application.screenRemoved.connect(self._screen_removed)

    def screens(self) -> list[ScreenInfo]:
        primary = self.application.primaryScreen()
        return [self._to_info(screen, screen is primary) for screen in self.application.screens()]

    def qt_screen(self, screen_id: str) -> QScreen | None:
        for screen in self.application.screens():
            info = self._to_info(screen, screen is self.application.primaryScreen())
            if info.id == screen_id:
                return screen
        return None

    def _screen_added(self, _screen: QScreen) -> None:
        self.screens_changed.emit()

    def _screen_removed(self, _screen: QScreen) -> None:
        self.screens_changed.emit()

    @staticmethod
    def _to_info(screen: QScreen, primary: bool) -> ScreenInfo:
        geometry = screen.geometry()
        identifier = (
            f"{screen.name()}|{geometry.x()}|{geometry.y()}|{geometry.width()}|{geometry.height()}"
        )
        return ScreenInfo(
            id=identifier,
            name=screen.name() or "Unnamed screen",
            x=geometry.x(),
            y=geometry.y(),
            width=geometry.width(),
            height=geometry.height(),
            device_pixel_ratio=screen.devicePixelRatio(),
            is_primary=primary,
        )


class MockScreenService(QObject):
    """Injectable screen service for CI and simulation tests."""

    screens_changed = Signal()

    def __init__(self, screens: Iterable[ScreenInfo]) -> None:
        super().__init__()
        self._screens = list(screens)

    def screens(self) -> list[ScreenInfo]:
        return list(self._screens)

    def qt_screen(self, _screen_id: str) -> QScreen | None:
        return None

    def set_screens(self, screens: Iterable[ScreenInfo]) -> None:
        self._screens = list(screens)
        self.screens_changed.emit()


def validate_role_assignment(
    broadcast_screen_id: str,
    venue_screen_id: str,
    *,
    simulation_mode: bool,
) -> tuple[bool, str]:
    if not broadcast_screen_id or not venue_screen_id:
        return False, "방송과 현장 화면을 모두 지정하십시오."
    if not simulation_mode and broadcast_screen_id == venue_screen_id:
        return False, "방송과 현장 출력에 같은 물리 화면을 지정할 수 없습니다."
    return True, ""
