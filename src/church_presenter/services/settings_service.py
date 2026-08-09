from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, TypeVar

from platformdirs import user_config_path

from church_presenter.domain.models import AppSettings, PreviewPreset, SubtitleStyle
from church_presenter.services.json_io import atomic_write_json

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class LoadResult:
    settings: AppSettings
    warning: str = ""
    backup_path: Path | None = None


class JsonModel(Protocol):
    def to_dict(self) -> dict[str, Any]: ...


class SettingsService:
    """Versioned JSON settings with atomic replacement and corruption backup."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or user_config_path("Church Presenter", "JinsolSeo")
        self.settings_path = self.config_dir / "settings.json"
        self.presets_path = self.config_dir / "subtitle_presets.json"
        self.preview_presets_path = self.config_dir / "preview_presets.json"

    def load(self) -> LoadResult:
        if not self.settings_path.exists():
            return LoadResult(AppSettings())
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("settings root must be an object")
            return LoadResult(AppSettings.from_dict(data))
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
            backup = self._backup_corrupt(self.settings_path)
            LOGGER.exception("Settings recovery used defaults: %s", error)
            return LoadResult(
                AppSettings(),
                "설정 파일이 손상되어 기본값으로 시작했습니다.",
                backup,
            )

    def save(self, settings: AppSettings) -> None:
        self._atomic_json_write(self.settings_path, settings.to_dict())

    def load_presets(self) -> tuple[dict[str, SubtitleStyle], str, str]:
        defaults = default_subtitle_presets()
        if not self.presets_path.exists():
            self.save_presets(defaults, "Lower Third")
            return defaults, "Lower Third", ""
        try:
            data = json.loads(self.presets_path.read_text(encoding="utf-8"))
            presets_data = data.get("presets", {})
            presets = {
                name: SubtitleStyle.from_dict(value)
                for name, value in presets_data.items()
                if isinstance(name, str) and isinstance(value, dict)
            }
            if not presets:
                presets = defaults
            default_name = str(data.get("default", next(iter(presets))))
            if default_name not in presets:
                default_name = next(iter(presets))
            return presets, default_name, ""
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
            self._backup_corrupt(self.presets_path)
            LOGGER.exception("Preset recovery used defaults: %s", error)
            self.save_presets(defaults, "Lower Third")
            return defaults, "Lower Third", "자막 프리셋이 손상되어 기본값을 복원했습니다."

    def save_presets(self, presets: dict[str, SubtitleStyle], default_name: str) -> None:
        if not presets:
            raise ValueError("At least one preset is required")
        if default_name not in presets:
            raise ValueError("Default preset must exist")
        payload = {
            "version": 1,
            "default": default_name,
            "presets": {name: style.to_dict() for name, style in presets.items()},
        }
        self._atomic_json_write(self.presets_path, payload)

    def load_preview_presets(self) -> tuple[list[PreviewPreset], str]:
        """Load ordered worship Preview presets, recovering corrupt data safely."""
        if not self.preview_presets_path.exists():
            return [], ""
        try:
            data = json.loads(self.preview_presets_path.read_text(encoding="utf-8"))
            return self._preview_presets_from_payload(data), ""
        except (
            OSError,
            UnicodeError,
            KeyError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ) as error:
            self._backup_corrupt(self.preview_presets_path)
            LOGGER.exception("Preview preset recovery used an empty list: %s", error)
            return [], "예배 순서 프리셋이 손상되어 빈 목록으로 복구했습니다."

    def save_preview_presets(self, presets: list[PreviewPreset]) -> None:
        """Atomically save presets in their operator-defined order."""
        self._atomic_json_write(
            self.preview_presets_path,
            self._preview_presets_payload(presets),
        )

    def load_preview_preset_file(self, path: Path) -> list[PreviewPreset]:
        """Load a user-selected worship-order JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return self._preview_presets_from_payload(data)

    def save_preview_preset_file(
        self,
        path: Path,
        presets: list[PreviewPreset],
    ) -> None:
        """Atomically save a portable worship-order JSON document."""
        self._atomic_json_write(path, self._preview_presets_payload(presets))

    @staticmethod
    def _preview_presets_from_payload(data: object) -> list[PreviewPreset]:
        if not isinstance(data, dict):
            raise TypeError("preview preset root must be an object")
        document_type = data.get("document_type")
        if document_type not in {None, "church_presenter_worship_order"}:
            raise ValueError("expected a Church Presenter worship-order document")
        rows = data.get("presets", [])
        if not isinstance(rows, list):
            raise TypeError("preview presets must be a list")
        version = data.get("version", 1)
        if version in {2, 3, 4}:
            presets = [PreviewPreset.from_preset_dict(row) for row in rows if isinstance(row, dict)]
        elif version == 1:
            presets = [
                PreviewPreset.from_dict(row).as_file_independent()
                for row in rows
                if isinstance(row, dict)
            ]
        else:
            raise ValueError(f"unsupported worship-order version: {version}")
        if len(presets) != len(rows):
            raise TypeError("each preview preset must be an object")
        names = [preset.name.casefold() for preset in presets]
        if len(names) != len(set(names)):
            raise ValueError("preview preset names must be unique")
        return presets

    @staticmethod
    def _preview_presets_payload(presets: list[PreviewPreset]) -> dict[str, Any]:
        names = [preset.name.casefold() for preset in presets]
        if len(names) != len(set(names)):
            raise ValueError("Preview preset names must be unique")
        return {
            "version": 4,
            "document_type": "church_presenter_worship_order",
            "presets": [preset.as_file_independent().to_preset_dict() for preset in presets],
        }

    def _atomic_json_write(self, path: Path, payload: dict[str, Any]) -> None:
        atomic_write_json(path, payload)

    @staticmethod
    def _backup_corrupt(path: Path) -> Path | None:
        if not path.exists():
            return None
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_name(f"{path.name}.corrupt-{stamp}")
        try:
            path.replace(backup)
        except OSError:
            LOGGER.exception("Could not back up corrupt file %s", path)
            return None
        return backup


def default_subtitle_presets() -> dict[str, SubtitleStyle]:
    """Return independent built-in sample presets."""
    return {
        "Lower Third": SubtitleStyle(),
        "Centered Worship": SubtitleStyle(
            font_size=64,
            y_ratio=0.55,
            background_opacity=0.25,
            max_width_ratio=0.78,
        ),
        "Large Announcement": SubtitleStyle(
            font_size=82,
            y_ratio=0.5,
            max_width_ratio=0.88,
            background_opacity=0.7,
            background_padding=28,
        ),
    }
