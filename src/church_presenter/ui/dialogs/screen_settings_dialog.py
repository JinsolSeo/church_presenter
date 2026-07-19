from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from church_presenter.domain.models import AppSettings, ScreenInfo
from church_presenter.services.audio_device_service import AudioOutputDeviceInfo
from church_presenter.services.screen_service import validate_role_assignment


class ScreenSettingsDialog(QDialog):
    """Screen role and virtual profile configuration."""

    def __init__(
        self,
        screens: list[ScreenInfo],
        settings: AppSettings,
        audio_outputs: Sequence[AudioOutputDeviceInfo] = (),
        default_audio_output_name: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Screen, Simulation & Audio Settings")
        self.settings = settings
        layout = QVBoxLayout(self)
        if len(screens) < 3:
            note = QLabel(
                "감지된 화면이 3개 미만입니다. 한 모니터 개발에는 Simulation Mode를 권장합니다."
            )
            note.setWordWrap(True)
            note.setProperty("role", "warning")
            layout.addWidget(note)
        form = QFormLayout()
        self.controller_combo = QComboBox()
        self.broadcast_combo = QComboBox()
        self.venue_combo = QComboBox()
        for combo in (self.controller_combo, self.broadcast_combo, self.venue_combo):
            combo.addItem("Not assigned", "")
            for screen in screens:
                combo.addItem(screen.label, screen.id)
        self._select(self.controller_combo, settings.controller_screen_id)
        self._select(self.broadcast_combo, settings.broadcast_screen_id)
        self._select(self.venue_combo, settings.venue_screen_id)
        form.addRow("Controller Screen", self.controller_combo)
        form.addRow("송출 화면", self.broadcast_combo)
        form.addRow("현장 화면", self.venue_combo)

        self.audio_output_combo = QComboBox()
        default_label = "시스템 기본 출력"
        if default_audio_output_name:
            default_label += f" · 현재 {default_audio_output_name}"
        self.audio_output_combo.addItem(default_label, "")
        for output in audio_outputs:
            suffix = " · 시스템 기본" if output.is_default else ""
            self.audio_output_combo.addItem(output.description + suffix, output.id)
        self._select(self.audio_output_combo, settings.audio_output_device_id)
        form.addRow("Audio Output", self.audio_output_combo)

        self.simulation_check = QCheckBox("Simulation Mode")
        self.simulation_check.setChecked(settings.simulation_mode)
        form.addRow(self.simulation_check)
        self.profile_combo = QComboBox()
        self.profile_combo.addItem("1280x720", (1280, 720))
        self.profile_combo.addItem("1920x1080", (1920, 1080))
        self.profile_combo.addItem("Custom", None)
        profile_index = self.profile_combo.findData(
            (settings.simulation_width, settings.simulation_height)
        )
        self.profile_combo.setCurrentIndex(profile_index if profile_index >= 0 else 2)
        form.addRow("Virtual profile", self.profile_combo)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(640, 7680)
        self.width_spin.setValue(settings.simulation_width)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(360, 4320)
        self.height_spin.setValue(settings.simulation_height)
        form.addRow("Virtual width", self.width_spin)
        form.addRow("Virtual height", self.height_spin)
        self.dpr_spin = QDoubleSpinBox()
        self.dpr_spin.setRange(0.5, 4.0)
        self.dpr_spin.setSingleStep(0.25)
        self.dpr_spin.setValue(settings.simulation_dpr)
        form.addRow("Virtual DPR", self.dpr_spin)
        self.broadcast_connected = QCheckBox("가상 송출 화면 연결됨")
        self.broadcast_connected.setChecked(settings.simulation_broadcast_connected)
        self.venue_connected = QCheckBox("가상 현장 화면 연결됨")
        self.venue_connected.setChecked(settings.simulation_venue_connected)
        form.addRow(self.broadcast_connected)
        form.addRow(self.venue_connected)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)

    @staticmethod
    def _select(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))

    def _profile_changed(self) -> None:
        profile = self.profile_combo.currentData()
        if profile:
            self.width_spin.setValue(profile[0])
            self.height_spin.setValue(profile[1])

    def _accept(self) -> None:
        simulation = self.simulation_check.isChecked()
        if not simulation:
            valid, error = validate_role_assignment(
                str(self.broadcast_combo.currentData()),
                str(self.venue_combo.currentData()),
                simulation_mode=False,
            )
            if not valid:
                QMessageBox.warning(self, "Screen assignment", error)
                return
        self.settings.controller_screen_id = str(self.controller_combo.currentData())
        self.settings.broadcast_screen_id = str(self.broadcast_combo.currentData())
        self.settings.venue_screen_id = str(self.venue_combo.currentData())
        self.settings.simulation_mode = simulation
        self.settings.simulation_width = self.width_spin.value()
        self.settings.simulation_height = self.height_spin.value()
        self.settings.simulation_dpr = self.dpr_spin.value()
        self.settings.simulation_broadcast_connected = self.broadcast_connected.isChecked()
        self.settings.simulation_venue_connected = self.venue_connected.isChecked()
        self.settings.audio_output_device_id = str(self.audio_output_combo.currentData())
        self.accept()
