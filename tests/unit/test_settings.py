from __future__ import annotations

import json
from pathlib import Path

import pytest

from church_presenter.domain.enums import ContentType, RepeatMode, SortField
from church_presenter.domain.models import (
    AppSettings,
    Content,
    CueReference,
    PreviewPreset,
    SubtitleStyle,
)
from church_presenter.services.settings_service import SettingsService


def test_settings_round_trip(tmp_path: Path) -> None:
    service = SettingsService(tmp_path)
    settings = AppSettings(
        pdf_folder="/portable/path",
        sort_field=SortField.MODIFIED,
        sort_descending=True,
        simulation_mode=True,
        current_theme="dark_modern",
        simulation_width=1920,
        simulation_height=1080,
        workspace_splitter_state="c3BsaXR0ZXItc3RhdGU=",
        last_pdf_page=7,
        pdf_page_orders={"/portable/path/service.pdf": [2, 0, 1]},
        pdf_link_outputs=True,
        linked_navigation_auto_take=True,
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


def test_legacy_settings_without_theme_uses_default(tmp_path: Path) -> None:
    service = SettingsService(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    service.settings_path.write_text('{"simulation_mode": true}', encoding="utf-8")

    result = service.load()

    assert result.warning == ""
    assert result.settings.current_theme == "light_professional"


def test_legacy_key_color_seeds_all_new_subtitle_sources(tmp_path: Path) -> None:
    service = SettingsService(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    service.settings_path.write_text('{"key_color": "#123456"}', encoding="utf-8")

    settings = service.load().settings

    assert settings.instant_text_key_color == "#123456"
    assert settings.praise_key_color == "#123456"
    assert settings.bible_key_color == "#123456"


def test_invalid_instant_text_group_size_falls_back_to_one(tmp_path: Path) -> None:
    service = SettingsService(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    service.settings_path.write_text('{"instant_text_group_size": 0}', encoding="utf-8")

    settings = service.load().settings

    assert settings.instant_text_group_size == 1


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
    assert loaded[1].broadcast_content.pdf_path == pdf_path
    assert loaded[1].venue_content.video_path == video_path.resolve()


@pytest.mark.parametrize(
    ("content", "expected_path", "expected_url"),
    [
        (Content.pdf(Path("/media/slides.pdf"), 4), Path("/media/slides.pdf"), ""),
        (Content.video(Path("/media/clip.mp4")), Path("/media/clip.mp4"), ""),
        (
            Content.youtube_video("https://www.youtube.com/watch?v=abcdefghijk"),
            None,
            "https://www.youtube.com/watch?v=abcdefghijk",
        ),
    ],
)
def test_cue_reference_retains_media_source(
    content: Content,
    expected_path: Path | None,
    expected_url: str,
) -> None:
    restored = CueReference.from_dict(CueReference.from_content(content).to_dict())

    assert restored.path == expected_path
    assert restored.url == expected_url
    assert CueReference.from_content(restored.to_content()) == restored
    assert Content.from_preset_dict(content.to_preset_dict()) == content.as_preset_reference()


def test_cue_reference_retains_subtitle_plan_source() -> None:
    plan_path = Path("/plans/praise.json")
    content = Content.subtitle(
        "Verse",
        2,
        SubtitleStyle(),
        "#00FF00",
        source="praise",
        reference="song-1:verse-1",
        source_path=plan_path,
    )

    restored = CueReference.from_dict(CueReference.from_content(content).to_dict())

    assert restored.path == plan_path
    assert restored.to_content().subtitle_path == plan_path


def test_cue_reference_normalizes_relative_source_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    relative = Path("weekly/service.pdf")
    content = Content(kind=ContentType.PDF_PAGE, pdf_path=relative, pdf_page=1)

    assert CueReference.from_content(content).path == (tmp_path / relative).resolve()


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
            "크로마키 빈 화면",
            Content.solid_color("#00FF00"),
            Content.solid_color("#0000FF"),
        ),
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
    assert '"document_type": "church_presenter_worship_order"' in path.read_text(encoding="utf-8")
    payload = path.read_text(encoding="utf-8")
    assert str(tmp_path) not in payload
    assert "찬양합니다." not in payload


def test_worship_order_v4_round_trip_retains_sources(tmp_path: Path) -> None:
    service = SettingsService(tmp_path / "settings")
    path = tmp_path / "service.json"
    pdf_path = tmp_path / "broadcast.pdf"
    youtube_url = "https://www.youtube.com/watch?v=abcdefghijk"
    preset = PreviewPreset(
        "Opening",
        Content.pdf(pdf_path, 2),
        Content.youtube_video(youtube_url),
    )

    service.save_preview_preset_file(path, [preset])
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["version"] == 4
    assert payload["presets"][0]["broadcast"]["path"] == str(pdf_path)
    assert payload["presets"][0]["venue"]["url"] == youtube_url
    assert service.load_preview_preset_file(path) == [preset.as_file_independent()]


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
            Content(
                kind=ContentType.PDF_PAGE,
                pdf_path=Path("/old/computer/service.pdf"),
                pdf_page=7,
            ),
        )
    ]


def test_worship_order_v4_preserves_semantic_subtitle_reference(tmp_path: Path) -> None:
    service = SettingsService(tmp_path / "settings")
    path = tmp_path / "order.json"
    preset = PreviewPreset(
        "성경 봉독",
        Content.subtitle(
            "본문",
            4,
            SubtitleStyle(),
            "#00FF00",
            source="bible",
            reference="JHN.3.16",
        ),
        Content.black(),
    )

    service.save_preview_preset_file(path, [preset])
    payload = json.loads(path.read_text(encoding="utf-8"))
    loaded = service.load_preview_preset_file(path)

    assert payload["version"] == 4
    assert payload["presets"][0]["broadcast"]["source"] == "bible"
    assert payload["presets"][0]["broadcast"]["reference"] == "JHN.3.16"
    assert loaded[0].broadcast_content.subtitle_reference == "JHN.3.16"


def test_future_worship_order_version_is_rejected(tmp_path: Path) -> None:
    service = SettingsService(tmp_path / "settings")
    path = tmp_path / "future.json"
    path.write_text('{"version": 99, "presets": []}', encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported worship-order version"):
        service.load_preview_preset_file(path)


def test_another_json_document_cannot_be_opened_as_worship_order(tmp_path: Path) -> None:
    service = SettingsService(tmp_path / "settings")
    path = tmp_path / "bible-plan.json"
    path.write_text(
        '{"document_type": "church_presenter_bible_plan", "schema_version": 1}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="worship-order"):
        service.load_preview_preset_file(path)
