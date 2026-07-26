from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, Slot
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget

from church_presenter.remote.protocol import KeyCommand, PointerCommand, WheelCommand

_BUTTONS = {
    "left": Qt.MouseButton.LeftButton,
    "middle": Qt.MouseButton.MiddleButton,
    "right": Qt.MouseButton.RightButton,
    "none": Qt.MouseButton.NoButton,
}
_KEYS = {
    "ArrowLeft": Qt.Key.Key_Left,
    "ArrowRight": Qt.Key.Key_Right,
    "ArrowUp": Qt.Key.Key_Up,
    "ArrowDown": Qt.Key.Key_Down,
    "PageUp": Qt.Key.Key_PageUp,
    "PageDown": Qt.Key.Key_PageDown,
    "Home": Qt.Key.Key_Home,
    "End": Qt.Key.Key_End,
    "Enter": Qt.Key.Key_Return,
    "Return": Qt.Key.Key_Return,
    "Escape": Qt.Key.Key_Escape,
    " ": Qt.Key.Key_Space,
    "Space": Qt.Key.Key_Space,
    "Spacebar": Qt.Key.Key_Space,
    "Tab": Qt.Key.Key_Tab,
    "Backspace": Qt.Key.Key_Backspace,
    "Delete": Qt.Key.Key_Delete,
}


def _modifiers(names: tuple[str, ...]) -> Qt.KeyboardModifier:
    result = Qt.KeyboardModifier.NoModifier
    mapping = {
        "alt": Qt.KeyboardModifier.AltModifier,
        "control": Qt.KeyboardModifier.ControlModifier,
        "meta": Qt.KeyboardModifier.MetaModifier,
        "shift": Qt.KeyboardModifier.ShiftModifier,
    }
    for name in names:
        result |= mapping[name]
    return result


class RemoteInputDispatcher(QObject):
    """Translate validated commands to normal Qt events on the GUI thread."""

    def __init__(
        self,
        target_provider: Callable[[], QWidget | None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._target_provider = target_provider
        self._pressed_buttons = Qt.MouseButton.NoButton
        self._pointer_widget: QWidget | None = None
        self.enabled = True

    @Slot(object)
    def dispatch(self, command: object) -> None:
        if not self.enabled or not isinstance(
            command,
            (PointerCommand, WheelCommand, KeyCommand),
        ):
            return
        if isinstance(command, PointerCommand):
            self._pointer(command)
        elif isinstance(command, WheelCommand):
            self._wheel(command)
        else:
            self._key(command)

    def _root_and_position(self, x: float, y: float) -> tuple[QWidget, QPoint] | None:
        root = self._target_provider()
        if root is None or not root.isVisible() or root.width() <= 0 or root.height() <= 0:
            return None
        position = QPoint(
            min(root.width() - 1, max(0, round(x * (root.width() - 1)))),
            min(root.height() - 1, max(0, round(y * (root.height() - 1)))),
        )
        return root, position

    def _pointer(self, command: PointerCommand) -> None:
        located = self._root_and_position(command.x, command.y)
        if located is None:
            return
        root, root_position = located
        hit = root.childAt(root_position) or root
        if command.action == "press":
            self._pointer_widget = hit
            if hit.focusPolicy() is not Qt.FocusPolicy.NoFocus:
                hit.setFocus(Qt.FocusReason.MouseFocusReason)
        target = self._pointer_widget or hit
        if target.window() is not root.window():
            target = hit
        local = target.mapFrom(root, root_position)
        button = _BUTTONS[command.button]
        if command.action == "press":
            self._pressed_buttons |= button
            event_type = QEvent.Type.MouseButtonPress
        elif command.action == "release":
            event_type = QEvent.Type.MouseButtonRelease
        elif command.action == "double":
            event_type = QEvent.Type.MouseButtonDblClick
        else:
            event_type = QEvent.Type.MouseMove
        global_position = root.mapToGlobal(root_position)
        event = QMouseEvent(
            event_type,
            QPointF(local),
            QPointF(root_position),
            QPointF(global_position),
            button,
            self._pressed_buttons,
            _modifiers(command.modifiers),
        )
        QApplication.sendEvent(target, event)
        if command.action == "release":
            self._pressed_buttons &= ~button
            self._pointer_widget = None

    def _wheel(self, command: WheelCommand) -> None:
        located = self._root_and_position(command.x, command.y)
        if located is None:
            return
        root, root_position = located
        target = root.childAt(root_position) or root
        local = target.mapFrom(root, root_position)
        event = QWheelEvent(
            QPointF(local),
            QPointF(root.mapToGlobal(root_position)),
            QPoint(),
            QPoint(-command.delta_x, -command.delta_y),
            self._pressed_buttons,
            _modifiers(command.modifiers),
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )
        QApplication.sendEvent(target, event)

    def _key(self, command: KeyCommand) -> None:
        root = self._target_provider()
        if root is None or not root.isVisible():
            return
        focus = QApplication.focusWidget()
        target = focus if focus is not None and focus.window() is root.window() else root
        text = command.text
        key = _KEYS.get(command.key)
        if key is None:
            source = text or command.key
            if not source:
                return
            key = Qt.Key(ord(source[0].upper())) if source[0].isascii() else Qt.Key.Key_unknown
            if not text and len(command.key) == 1:
                text = command.key
        event_type = (
            QEvent.Type.KeyPress if command.action == "press" else QEvent.Type.KeyRelease
        )
        event = QKeyEvent(event_type, key, _modifiers(command.modifiers), text)
        QApplication.sendEvent(target, event)
