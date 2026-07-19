from __future__ import annotations

from base64 import urlsafe_b64encode
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal
from PySide6.QtMultimedia import QAudioDevice, QMediaDevices


@dataclass(frozen=True, slots=True)
class AudioOutputDeviceInfo:
    """Stable UI description of one physical audio output device."""

    id: str
    description: str
    is_default: bool


class AudioDeviceService(QObject):
    """Discover audio outputs and resolve persisted device identifiers."""

    outputs_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._media_devices = QMediaDevices(self)
        self._media_devices.audioOutputsChanged.connect(self.outputs_changed)

    def outputs(self) -> list[AudioOutputDeviceInfo]:
        return [
            AudioOutputDeviceInfo(
                id=self._device_id(device),
                description=device.description() or "Unnamed audio output",
                is_default=device.isDefault(),
            )
            for device in QMediaDevices.audioOutputs()
        ]

    def default_description(self) -> str:
        device = QMediaDevices.defaultAudioOutput()
        return "" if device.isNull() else device.description()

    def resolve(self, device_id: str) -> QAudioDevice | None:
        if not device_id:
            return QAudioDevice()
        return next(
            (
                device
                for device in QMediaDevices.audioOutputs()
                if self._device_id(device) == device_id
            ),
            None,
        )

    def is_available(self, device_id: str) -> bool:
        return not device_id or self.resolve(device_id) is not None

    @staticmethod
    def _device_id(device: QAudioDevice) -> str:
        return urlsafe_b64encode(device.id().data()).decode("ascii")
