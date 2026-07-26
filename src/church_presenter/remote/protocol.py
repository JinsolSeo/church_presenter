from __future__ import annotations

import json
from dataclasses import dataclass

MAX_INPUT_MESSAGE_BYTES = 4096
MAX_TEXT_LENGTH = 16


@dataclass(frozen=True, slots=True)
class PointerCommand:
    action: str
    x: float
    y: float
    button: str
    modifiers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WheelCommand:
    x: float
    y: float
    delta_x: int
    delta_y: int
    modifiers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KeyCommand:
    action: str
    key: str
    code: str
    text: str
    modifiers: tuple[str, ...] = ()


type RemoteCommand = PointerCommand | WheelCommand | KeyCommand

_POINTER_ACTIONS = {"press", "move", "release", "double"}
_BUTTONS = {"left", "middle", "right", "none"}
_KEY_ACTIONS = {"press", "release"}
_MODIFIERS = {"alt", "control", "meta", "shift"}


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if 0.0 <= result <= 1.0 else None


def _modifiers(value: object) -> tuple[str, ...] | None:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > len(_MODIFIERS):
        return None
    normalized = tuple(str(item).lower() for item in value)
    if any(item not in _MODIFIERS for item in normalized):
        return None
    return tuple(dict.fromkeys(normalized))


def parse_input_message(payload: str) -> RemoteCommand | None:
    """Validate an untrusted browser input message."""
    if len(payload.encode("utf-8")) > MAX_INPUT_MESSAGE_BYTES:
        return None
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    kind = data.get("type")
    modifiers = _modifiers(data.get("modifiers"))
    if modifiers is None:
        return None

    if kind == "pointer":
        action = data.get("action")
        button = data.get("button", "none")
        x = _number(data.get("x"))
        y = _number(data.get("y"))
        if (
            action not in _POINTER_ACTIONS
            or button not in _BUTTONS
            or x is None
            or y is None
        ):
            return None
        return PointerCommand(str(action), x, y, str(button), modifiers)

    if kind == "wheel":
        x = _number(data.get("x"))
        y = _number(data.get("y"))
        delta_x = data.get("deltaX", 0)
        delta_y = data.get("deltaY", 0)
        if (
            x is None
            or y is None
            or isinstance(delta_x, bool)
            or isinstance(delta_y, bool)
            or not isinstance(delta_x, (int, float))
            or not isinstance(delta_y, (int, float))
        ):
            return None
        return WheelCommand(
            x,
            y,
            max(-4000, min(4000, round(delta_x))),
            max(-4000, min(4000, round(delta_y))),
            modifiers,
        )

    if kind == "key":
        action = data.get("action")
        key = data.get("key", "")
        code = data.get("code", "")
        text = data.get("text", "")
        if (
            action not in _KEY_ACTIONS
            or not isinstance(key, str)
            or not isinstance(code, str)
            or not isinstance(text, str)
            or len(key) > 32
            or len(code) > 48
            or len(text) > MAX_TEXT_LENGTH
        ):
            return None
        if not key and not text:
            return None
        return KeyCommand(str(action), key, code, text, modifiers)
    return None
