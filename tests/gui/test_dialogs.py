from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QPalette

from church_presenter.domain.enums import HorizontalAnchor, TextAlignment, VerticalAnchor
from church_presenter.domain.models import AppSettings, ScreenInfo, SubtitleStyle
from church_presenter.services.audio_device_service import AudioOutputDeviceInfo
from church_presenter.services.pdf_service import PdfRenderCoordinator
from church_presenter.services.settings_service import SettingsService
from church_presenter.ui.dialogs.screen_settings_dialog import ScreenSettingsDialog
from church_presenter.ui.dialogs.subtitle_style_dialog import (
    SubtitleStyleDialog,
    conflicting_colors,
)
from church_presenter.ui.styles import apply_application_style


def test_style_dialog_has_default_presets_and_key_conflict(qtbot, tmp_path: Path) -> None:
    dialog = SubtitleStyleDialog(
        SettingsService(tmp_path),
        PdfRenderCoordinator(),
        SubtitleStyle(),
        "#00FF00",
        "Lower Third",
    )
    qtbot.addWidget(dialog)
    names = {dialog.preset_combo.itemData(index) for index in range(dialog.preset_combo.count())}
    assert names == {"Lower Third", "Centered Worship", "Large Announcement"}
    green_style = SubtitleStyle(text_color="#00FE00")
    assert "글자" in conflicting_colors(green_style, "#00FF00")
    dialog.alignment.setCurrentIndex(dialog.alignment.findData(TextAlignment.LEFT))
    dialog.horizontal_anchor.setCurrentIndex(
        dialog.horizontal_anchor.findData(HorizontalAnchor.RIGHT)
    )
    dialog.vertical_anchor.setCurrentIndex(dialog.vertical_anchor.findData(VerticalAnchor.TOP))
    selected_style = dialog._style()
    assert selected_style.alignment is TextAlignment.LEFT
    assert selected_style.horizontal_anchor is HorizontalAnchor.RIGHT
    assert selected_style.vertical_anchor is VerticalAnchor.TOP


def test_screen_settings_exposes_virtual_profile_and_connections(qtbot) -> None:
    settings = AppSettings(
        simulation_mode=True,
        simulation_width=1920,
        simulation_height=1080,
        audio_output_device_id="usb-speaker",
    )
    dialog = ScreenSettingsDialog(
        [ScreenInfo("one", "Single", 0, 0, 1920, 1080, 2.0, True)],
        settings,
        [AudioOutputDeviceInfo("usb-speaker", "USB Speaker", False)],
        "MacBook Speakers",
    )
    qtbot.addWidget(dialog)
    assert dialog.simulation_check.isChecked()
    assert dialog.width_spin.value() == 1920
    assert dialog.height_spin.value() == 1080
    assert dialog.broadcast_connected.isChecked()
    assert dialog.venue_connected.isChecked()
    assert dialog.broadcast_connected.text() == "가상 송출 화면 연결됨"
    assert dialog.venue_connected.text() == "가상 현장 화면 연결됨"
    assert dialog.audio_output_combo.currentData() == "usb-speaker"
    assert "MacBook Speakers" in dialog.audio_output_combo.itemText(0)

    dialog.audio_output_combo.setCurrentIndex(0)
    dialog._accept()
    assert settings.audio_output_device_id == ""


def test_application_palette_keeps_text_visible(qapp) -> None:
    apply_application_style(qapp)
    palette = qapp.palette()
    assert palette.color(QPalette.ColorRole.Button) != palette.color(QPalette.ColorRole.ButtonText)
    assert palette.color(QPalette.ColorRole.Base) != palette.color(QPalette.ColorRole.Text)
