from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from PySide6.QtGui import QPalette

from church_presenter.ui.styles import DEFAULT_THEME_ID, ThemeManager

BUILTIN_THEME_IDS = {
    "light_professional",
    "dark_modern",
    "minimalist_light",
    "warm_linen",
    "deep_ocean",
    "graphite_violet",
}


def _builtin_theme(theme_id: str = DEFAULT_THEME_ID) -> dict[str, object]:
    resource = files("church_presenter.ui").joinpath("themes", f"{theme_id}.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _write_theme(root: Path, data: dict[str, object], filename: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / filename).write_text(json.dumps(data), encoding="utf-8")


def _relative_luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    first_luminance = _relative_luminance(first)
    second_luminance = _relative_luminance(second)
    lighter = max(first_luminance, second_luminance)
    darker = min(first_luminance, second_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def test_builtin_themes_are_discovered_and_apply(qapp) -> None:
    manager = ThemeManager()

    assert {theme.id for theme in manager.available_themes()} == BUILTIN_THEME_IDS

    for theme_id in BUILTIN_THEME_IDS:
        assert manager.apply_theme(qapp, theme_id) == theme_id
        assert manager.current_theme_id() == theme_id
        assert "{{" not in qapp.styleSheet()
        palette = qapp.palette()
        assert palette.color(QPalette.ColorRole.Base) != palette.color(QPalette.ColorRole.Text)


def test_builtin_action_text_meets_normal_text_contrast() -> None:
    for theme_id in BUILTIN_THEME_IDS:
        theme = _builtin_theme(theme_id)
        colors = theme["colors"]
        assert isinstance(colors, dict)
        foreground = colors["text_on_accent"]
        assert isinstance(foreground, str)
        for token in (
            "accent",
            "accent_hover",
            "accent_pressed",
            "live",
            "live_hover",
            "live_pressed",
            "danger",
        ):
            background = colors[token]
            assert isinstance(background, str)
            assert _contrast(foreground, background) >= 4.5


def test_missing_or_invalid_theme_falls_back_without_crashing(qapp, tmp_path: Path) -> None:
    _write_theme(tmp_path, _builtin_theme(), "light_professional.json")
    (tmp_path / "broken.json").write_text("{broken", encoding="utf-8")
    manager = ThemeManager(theme_root=tmp_path)

    assert manager.apply_theme(qapp, "broken") == DEFAULT_THEME_ID
    assert manager.current_theme_id() == DEFAULT_THEME_ID
    assert manager.last_warning


def test_theme_with_missing_required_token_is_not_available(tmp_path: Path) -> None:
    valid = _builtin_theme()
    invalid = _builtin_theme()
    invalid["meta"] = {
        "id": "missing_token",
        "name": "Missing Token",
        "mode": "light",
        "version": 1,
    }
    del invalid["colors"]["accent"]  # type: ignore[index]
    _write_theme(tmp_path, valid, "light_professional.json")
    _write_theme(tmp_path, invalid, "missing_token.json")

    manager = ThemeManager(theme_root=tmp_path)

    assert [theme.id for theme in manager.available_themes()] == [DEFAULT_THEME_ID]


def test_new_theme_json_is_discovered_without_recreating_manager(tmp_path: Path) -> None:
    _write_theme(tmp_path, _builtin_theme(), "light_professional.json")
    manager = ThemeManager(theme_root=tmp_path)
    assert [theme.id for theme in manager.available_themes()] == [DEFAULT_THEME_ID]

    added = _builtin_theme()
    added["meta"] = {
        "id": "added_later",
        "name": "Added Later",
        "mode": "light",
        "version": 1,
    }
    _write_theme(tmp_path, added, "added_later.json")

    assert {theme.id for theme in manager.available_themes()} == {
        DEFAULT_THEME_ID,
        "added_later",
    }


def test_duplicate_theme_ids_are_rejected(tmp_path: Path) -> None:
    first = _builtin_theme()
    second = _builtin_theme()
    second["meta"] = {
        "id": DEFAULT_THEME_ID,
        "name": "Duplicate",
        "mode": "light",
        "version": 1,
    }
    _write_theme(tmp_path, first, "first.json")
    _write_theme(tmp_path, second, "second.json")

    assert ThemeManager(theme_root=tmp_path).available_themes() == []


def test_unknown_qss_placeholder_uses_safe_native_fallback(qapp, tmp_path: Path) -> None:
    _write_theme(tmp_path, _builtin_theme(), "light_professional.json")
    template = tmp_path / "invalid.qss"
    template.write_text("QWidget { color: {{unknown_token}}; }", encoding="utf-8")
    manager = ThemeManager(theme_root=tmp_path, qss_template=template)

    assert manager.apply_theme(qapp, DEFAULT_THEME_ID) == ""
    assert qapp.styleSheet() == ""
    assert manager.last_warning
