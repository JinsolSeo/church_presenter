from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

LOGGER = logging.getLogger(__name__)

DEFAULT_THEME_ID = "light_professional"
_THEME_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
_PLACEHOLDER_PATTERN = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")

_REQUIRED_COLORS = {
    "window_bg",
    "surface",
    "surface_alt",
    "surface_hover",
    "border",
    "border_strong",
    "text_primary",
    "text_secondary",
    "text_disabled",
    "text_on_accent",
    "accent",
    "accent_hover",
    "accent_pressed",
    "accent_soft",
    "preview",
    "preview_soft",
    "live",
    "live_hover",
    "live_pressed",
    "live_soft",
    "success",
    "warning",
    "danger",
    "selection",
    "focus",
    "disabled_bg",
    "slider_groove",
    "slider_handle",
    "scrollbar_handle",
}
_REQUIRED_METRICS = {
    "control_height",
    "button_height",
    "take_button_height",
    "radius",
    "panel_radius",
    "border_width",
    "monitor_border_width",
    "icon_size",
    "scrollbar_width",
    "compact_control_height",
    "compact_button_height",
    "compact_take_button_height",
    "compact_scrollbar_width",
}
_REQUIRED_SPACING = {
    "xs",
    "sm",
    "md",
    "lg",
    "xl",
    "compact_xs",
    "compact_sm",
    "compact_md",
}
_REQUIRED_TYPOGRAPHY = {
    "font_family",
    "font_size",
    "caption_size",
    "section_title_size",
    "monitor_title_size",
    "take_button_size",
    "page_title_size",
    "compact_font_size",
    "compact_caption_size",
    "compact_section_title_size",
    "compact_monitor_title_size",
    "compact_take_button_size",
    "compact_page_title_size",
}


class ThemeValidationError(ValueError):
    """Raised when a theme cannot safely produce an application stylesheet."""


@dataclass(frozen=True, slots=True)
class ThemeInfo:
    """Metadata shown in the appearance selector."""

    id: str
    name: str
    mode: str
    version: int


@dataclass(frozen=True, slots=True)
class _LoadedTheme:
    info: ThemeInfo
    data: dict[str, Any]
    source_name: str


class ThemeManager(QObject):
    """Discover, validate, render, and apply JSON-backed GUI themes."""

    theme_changed = Signal(str)

    def __init__(
        self,
        theme_root: Traversable | None = None,
        qss_template: Traversable | None = None,
    ) -> None:
        super().__init__()
        ui_resources = files("church_presenter.ui")
        self.theme_root = theme_root or ui_resources.joinpath("themes")
        self.qss_template = qss_template or ui_resources.joinpath("app.qss")
        self._current_theme_id = ""
        self._current_theme: _LoadedTheme | None = None
        self.last_warning = ""

    def available_themes(self) -> list[ThemeInfo]:
        """Return valid, uniquely identified themes discovered at call time."""
        themes, _errors = self._discover_themes()
        return [theme.info for theme in sorted(themes.values(), key=lambda item: item.info.name)]

    def current_theme_id(self) -> str:
        """Return the applied theme id, or an empty string before first apply."""
        return self._current_theme_id

    def current_value(self, section: str, token: str) -> Any:
        """Return a token from the active theme for layout values QSS cannot control."""
        if self._current_theme is None:
            raise RuntimeError("No theme has been applied")
        return self._current_theme.data[section][token]

    def apply_theme(self, application: QApplication, theme_id: str) -> str:
        """Apply a requested theme and safely fall back to the built-in default."""
        themes, errors = self._discover_themes()
        requested = theme_id or DEFAULT_THEME_ID
        selected = themes.get(requested)
        self.last_warning = ""
        if selected is None:
            selected = themes.get(DEFAULT_THEME_ID)
            detail = errors.get(requested, "테마가 존재하지 않습니다.")
            self.last_warning = (
                f"테마 '{requested}'을 적용할 수 없어 Light Professional을 사용합니다. "
                f"{detail}"
            )
            LOGGER.warning("Theme fallback for %s: %s", requested, detail)
        if selected is None:
            detail = errors.get(DEFAULT_THEME_ID, "기본 테마를 찾을 수 없습니다.")
            LOGGER.error("Default theme is unavailable: %s", detail)
            self.last_warning = "기본 테마를 읽을 수 없어 운영체제 기본 스타일을 사용합니다."
            application.setStyleSheet("")
            self._current_theme = None
            self._current_theme_id = ""
            return ""

        try:
            stylesheet = self._render_stylesheet(selected.data)
        except (OSError, UnicodeError, ThemeValidationError):
            LOGGER.exception("Could not render theme %s", selected.info.id)
            self.last_warning = "테마 스타일을 만들 수 없어 운영체제 기본 스타일을 사용합니다."
            application.setStyleSheet("")
            self._current_theme = None
            self._current_theme_id = ""
            return ""

        application.setPalette(self._palette(selected.data["colors"]))
        application.setStyleSheet(stylesheet)
        self._current_theme = selected
        self._current_theme_id = selected.info.id
        self.theme_changed.emit(selected.info.id)
        return selected.info.id

    def _discover_themes(self) -> tuple[dict[str, _LoadedTheme], dict[str, str]]:
        themes: dict[str, _LoadedTheme] = {}
        errors: dict[str, str] = {}
        duplicate_ids: set[str] = set()
        try:
            candidates = sorted(
                (item for item in self.theme_root.iterdir() if item.name.endswith(".json")),
                key=lambda item: item.name,
            )
        except (FileNotFoundError, OSError) as error:
            LOGGER.exception("Could not enumerate application themes")
            return {}, {DEFAULT_THEME_ID: str(error)}

        for candidate in candidates:
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                loaded = self._validate_theme(data, candidate.name)
            except (OSError, UnicodeError, json.JSONDecodeError, ThemeValidationError) as error:
                errors[candidate.name.removesuffix(".json")] = str(error)
                LOGGER.warning("Ignoring invalid theme %s: %s", candidate.name, error)
                continue
            theme_id = loaded.info.id
            if theme_id in themes or theme_id in duplicate_ids:
                themes.pop(theme_id, None)
                duplicate_ids.add(theme_id)
                errors[theme_id] = "동일한 theme id가 두 번 정의되었습니다."
                continue
            themes[theme_id] = loaded
        return themes, errors

    @staticmethod
    def _validate_theme(data: object, source_name: str) -> _LoadedTheme:
        if not isinstance(data, dict):
            raise ThemeValidationError("theme root must be an object")
        for section in ("meta", "colors", "metrics", "spacing", "typography"):
            if not isinstance(data.get(section), dict):
                raise ThemeValidationError(f"missing or invalid section: {section}")

        meta = data["meta"]
        theme_id = meta.get("id")
        name = meta.get("name")
        mode = meta.get("mode")
        version = meta.get("version")
        if not isinstance(theme_id, str) or not _THEME_ID_PATTERN.fullmatch(theme_id):
            raise ThemeValidationError("meta.id must be a snake_case identifier")
        if not isinstance(name, str) or not name.strip():
            raise ThemeValidationError("meta.name must be a non-empty string")
        if mode not in {"light", "dark"}:
            raise ThemeValidationError("meta.mode must be light or dark")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ThemeValidationError("meta.version must be a positive integer")

        ThemeManager._validate_required_tokens(data["colors"], _REQUIRED_COLORS, "colors")
        for token, value in data["colors"].items():
            if not isinstance(value, str) or not _COLOR_PATTERN.fullmatch(value):
                raise ThemeValidationError(f"invalid color token: {token}")

        ThemeManager._validate_required_tokens(data["metrics"], _REQUIRED_METRICS, "metrics")
        ThemeManager._validate_required_tokens(data["spacing"], _REQUIRED_SPACING, "spacing")
        for section in ("metrics", "spacing"):
            for token, value in data[section].items():
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ThemeValidationError(f"{section}.{token} must be a non-negative integer")

        ThemeManager._validate_required_tokens(
            data["typography"],
            _REQUIRED_TYPOGRAPHY,
            "typography",
        )
        if not isinstance(data["typography"]["font_family"], str):
            raise ThemeValidationError("typography.font_family must be a string")
        for token, value in data["typography"].items():
            if token == "font_family":
                continue
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ThemeValidationError(f"typography.{token} must be a positive integer")

        return _LoadedTheme(ThemeInfo(theme_id, name.strip(), mode, version), data, source_name)

    @staticmethod
    def _validate_required_tokens(
        values: dict[str, Any],
        required: set[str],
        section: str,
    ) -> None:
        missing = sorted(required - values.keys())
        if missing:
            raise ThemeValidationError(f"missing {section} tokens: {', '.join(missing)}")

    def _render_stylesheet(self, data: dict[str, Any]) -> str:
        template = self.qss_template.read_text(encoding="utf-8")
        tokens: dict[str, Any] = {}
        for section in ("colors", "metrics", "spacing", "typography"):
            for key, value in data[section].items():
                if key in tokens:
                    raise ThemeValidationError(f"duplicate token name across sections: {key}")
                tokens[key] = value
        placeholders = set(_PLACEHOLDER_PATTERN.findall(template))
        missing = sorted(placeholders - tokens.keys())
        if missing:
            raise ThemeValidationError(f"QSS references unknown tokens: {', '.join(missing)}")
        rendered = _PLACEHOLDER_PATTERN.sub(lambda match: str(tokens[match.group(1)]), template)
        if "{{" in rendered or "}}" in rendered:
            raise ThemeValidationError("QSS contains an unresolved placeholder")
        return rendered

    @staticmethod
    def _palette(colors: dict[str, str]) -> QPalette:
        palette = QPalette()
        role_colors = {
            QPalette.ColorRole.Window: colors["window_bg"],
            QPalette.ColorRole.WindowText: colors["text_primary"],
            QPalette.ColorRole.Base: colors["surface"],
            QPalette.ColorRole.AlternateBase: colors["surface_alt"],
            QPalette.ColorRole.Text: colors["text_primary"],
            QPalette.ColorRole.Button: colors["surface"],
            QPalette.ColorRole.ButtonText: colors["text_primary"],
            QPalette.ColorRole.Highlight: colors["selection"],
            QPalette.ColorRole.HighlightedText: colors["text_primary"],
            QPalette.ColorRole.ToolTipBase: colors["surface_alt"],
            QPalette.ColorRole.ToolTipText: colors["text_primary"],
        }
        for role, color in role_colors.items():
            palette.setColor(role, QColor(color))
        for role in (
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.Text,
            QPalette.ColorRole.ButtonText,
        ):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors["text_disabled"]))
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.Button,
            QColor(colors["disabled_bg"]),
        )
        return palette


def apply_application_style(
    application: QApplication,
    theme_id: str = DEFAULT_THEME_ID,
) -> ThemeManager:
    """Compatibility helper that applies one theme and returns its manager."""
    manager = ThemeManager()
    manager.apply_theme(application, theme_id)
    return manager
