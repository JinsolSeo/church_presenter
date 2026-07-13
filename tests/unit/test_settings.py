from __future__ import annotations

from pathlib import Path

from church_presenter.domain.enums import RepeatMode, SortField
from church_presenter.domain.models import AppSettings, SubtitleStyle
from church_presenter.services.settings_service import SettingsService


def test_settings_round_trip(tmp_path: Path) -> None:
    service = SettingsService(tmp_path)
    settings = AppSettings(
        pdf_folder="/portable/path",
        sort_field=SortField.MODIFIED,
        sort_descending=True,
        simulation_mode=True,
        simulation_width=1920,
        simulation_height=1080,
        last_pdf_page=7,
        pdf_page_orders={"/portable/path/service.pdf": [2, 0, 1]},
        pdf_link_outputs=True,
        key_color="#0000FF",
        video_folder="/portable/videos",
        audio_folder="/portable/audio",
        video_sort_field=SortField.MODIFIED,
        audio_sort_descending=True,
        video_volume=63,
        music_volume=42,
        video_muted=True,
        music_muted=True,
        fade_duration_ms=700,
        last_video_file="/portable/videos/service.mp4",
        last_audio_file="/portable/audio/music.wav",
        last_playlist="/portable/service.json",
        repeat_mode=RepeatMode.ALL,
    )
    service.save(settings)
    result = service.load()
    assert result.warning == ""
    assert result.settings == settings


def test_corrupt_settings_are_backed_up(tmp_path: Path) -> None:
    service = SettingsService(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    service.settings_path.write_text("{broken", encoding="utf-8")
    result = service.load()
    assert result.settings == AppSettings()
    assert result.warning
    assert result.backup_path is not None
    assert result.backup_path.exists()
    assert not service.settings_path.exists()


def test_presets_round_trip_and_default(tmp_path: Path) -> None:
    service = SettingsService(tmp_path)
    presets = {"Custom": SubtitleStyle(font_size=71, text_color="#F0F0F0")}
    assert presets["Custom"].font_size == 71
    service.save_presets(presets, "Custom")
    loaded, default, warning = service.load_presets()
    assert warning == ""
    assert default == "Custom"
    assert loaded == presets
