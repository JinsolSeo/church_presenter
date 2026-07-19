from __future__ import annotations

import json
from pathlib import Path

from church_presenter.domain.enums import ContentType, RepeatMode, SortField
from church_presenter.domain.models import AppSettings, Content, PreviewPreset, SubtitleStyle
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
        preview_preset_file="/portable/path/sunday-order.json",
        key_color="#0000FF",
        video_folder="/portable/videos",
        audio_folder="/portable/audio",
        video_sort_field=SortField.MODIFIED,
        audio_sort_descending=True,
        video_volume=63,
        music_volume=42,
        video_muted=True,
        music_muted=True,
        audio_output_device_id="dXNiLXNwZWFrZXI=",
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


def test_preview_presets_round_trip_in_worship_order(tmp_path: Path) -> None:
    service = SettingsService(tmp_path)
    pdf_path = tmp_path / "worship.pdf"
    video_path = tmp_path / "welcome.mp4"
    presets = [
        PreviewPreset(
            "예배 시작",
            Content.subtitle("예배를 시작합니다.", 0, SubtitleStyle(), "#00FF00"),
            Content.black(),
        ),
        PreviewPreset(
            "말씀",
            Content.pdf(pdf_path, 3),
            Content.video(video_path),
        ),
    ]

    service.save_preview_presets(presets)
    loaded, warning = service.load_preview_presets()

    assert warning == ""
    assert loaded == [preset.as_file_independent() for preset in presets]
    assert [preset.name for preset in loaded] == ["예배 시작", "말씀"]
    assert loaded[1].broadcast_content.pdf_path is None
    assert loaded[1].venue_content.video_path is None


def test_corrupt_preview_presets_are_backed_up(tmp_path: Path) -> None:
    service = SettingsService(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    service.preview_presets_path.write_text('{"presets": "broken"}', encoding="utf-8")

    loaded, warning = service.load_preview_presets()

    assert loaded == []
    assert warning
    assert not service.preview_presets_path.exists()
    assert list(tmp_path.glob("preview_presets.json.corrupt-*"))


def test_worship_order_can_be_saved_and_loaded_as_a_file(tmp_path: Path) -> None:
    service = SettingsService(tmp_path / "settings")
    path = tmp_path / "2026-07-19-worship-order.json"
    presets = [
        PreviewPreset("예배 시작", Content.black(), Content.black()),
        PreviewPreset(
            "찬양",
            Content.subtitle("찬양합니다.", 0, SubtitleStyle(), "#00FF00"),
            Content.black(),
        ),
    ]

    service.save_preview_preset_file(path, presets)

    assert path.is_file()
    assert service.load_preview_preset_file(path) == [
        preset.as_file_independent() for preset in presets
    ]
    assert '"document_type": "church_presenter_worship_order"' in path.read_text(
        encoding="utf-8"
    )
    payload = path.read_text(encoding="utf-8")
    assert str(tmp_path) not in payload
    assert "찬양합니다." not in payload


def test_legacy_worship_order_is_migrated_to_positions(tmp_path: Path) -> None:
    service = SettingsService(tmp_path / "settings")
    path = tmp_path / "legacy.json"
    legacy = PreviewPreset(
        "말씀",
        Content.subtitle("저장 당시 자막", 4, SubtitleStyle(), "#00FF00"),
        Content.pdf(Path("/old/computer/service.pdf"), 7),
    )
    path.write_text(
        json.dumps(
            {"version": 1, "presets": [legacy.to_dict()]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = service.load_preview_preset_file(path)

    assert loaded == [
        PreviewPreset(
            "말씀",
            Content(kind=ContentType.SUBTITLE_KEY, subtitle_card_index=4),
            Content(kind=ContentType.PDF_PAGE, pdf_page=7),
        )
    ]
