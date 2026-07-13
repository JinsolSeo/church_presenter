from __future__ import annotations

from enum import StrEnum

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from church_presenter.domain.enums import HorizontalAnchor, TextAlignment, VerticalAnchor
from church_presenter.domain.models import Content, SubtitleStyle
from church_presenter.rendering.output_surface import AspectRatioContainer, OutputSurface
from church_presenter.services.pdf_service import PdfRenderCoordinator
from church_presenter.services.settings_service import SettingsService
from church_presenter.ui.widgets.color_button import ColorButton


class SubtitleStyleDialog(QDialog):
    """Edit subtitle style and named presets without mutating Live content."""

    def __init__(
        self,
        settings_service: SettingsService,
        coordinator: PdfRenderCoordinator,
        style: SubtitleStyle,
        key_color: str,
        current_preset: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Subtitle Style Settings")
        self.resize(860, 800)
        self.settings_service = settings_service
        self.presets, self.default_preset, warning = settings_service.load_presets()
        self.result_style = style
        self.result_key_color = key_color
        self.result_preset = current_preset
        root = QVBoxLayout(self)
        if warning:
            warning_label = QLabel(warning)
            warning_label.setStyleSheet("color:#b45309;font-weight:700;")
            root.addWidget(warning_label)

        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox()
        self._populate_presets(current_preset)
        load_button = QPushButton("불러오기")
        save_button = QPushButton("덮어쓰기")
        new_button = QPushButton("새 프리셋")
        rename_button = QPushButton("이름 변경")
        delete_button = QPushButton("삭제")
        default_button = QPushButton("기본 지정")
        for widget in (
            self.preset_combo,
            load_button,
            save_button,
            new_button,
            rename_button,
            delete_button,
            default_button,
        ):
            preset_row.addWidget(widget)
        root.addLayout(preset_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_host = QWidget()
        form = QFormLayout(form_host)
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont(style.font_family))
        self.font_size = self._double(10, 180, style.font_size, 1)
        self.text_color = ColorButton(style.text_color)
        self.bold = QCheckBox()
        self.bold.setChecked(style.bold)
        self.outline_color = ColorButton(style.outline_color)
        self.outline_width = self._double(0, 16, style.outline_width, 0.5)
        self.shadow_color = ColorButton(style.shadow_color)
        self.shadow_opacity = self._double(0, 1, style.shadow_opacity, 0.05)
        self.shadow_x = self._double(-30, 30, style.shadow_offset_x, 1)
        self.shadow_y = self._double(-30, 30, style.shadow_offset_y, 1)
        self.background_color = ColorButton(style.background_color)
        self.background_opacity = self._double(0, 1, style.background_opacity, 0.05)
        self.background_padding = self._double(0, 80, style.background_padding, 1)
        self.x_ratio = self._double(0, 1, style.x_ratio, 0.01)
        self.y_ratio = self._double(0, 1, style.y_ratio, 0.01)
        self.max_width = self._double(0.1, 1, style.max_width_ratio, 0.01)
        self.line_spacing = self._double(0.8, 3, style.line_spacing, 0.05)
        self.alignment = self._enum_combo(TextAlignment, style.alignment)
        self.horizontal_anchor = self._enum_combo(HorizontalAnchor, style.horizontal_anchor)
        self.vertical_anchor = self._enum_combo(VerticalAnchor, style.vertical_anchor)
        self.key_color = ColorButton(key_color)
        rows: tuple[tuple[str, QWidget], ...] = (
            ("글꼴", self.font_combo),
            ("글자 크기", self.font_size),
            ("글자 색상", self.text_color),
            ("굵게", self.bold),
            ("외곽선 색상", self.outline_color),
            ("외곽선 두께", self.outline_width),
            ("그림자 색상", self.shadow_color),
            ("그림자 투명도", self.shadow_opacity),
            ("그림자 X 오프셋", self.shadow_x),
            ("그림자 Y 오프셋", self.shadow_y),
            ("배경 색상", self.background_color),
            ("배경 투명도", self.background_opacity),
            ("배경 패딩", self.background_padding),
            ("수평 위치 비율", self.x_ratio),
            ("수직 위치 비율", self.y_ratio),
            ("최대 폭 비율", self.max_width),
            ("줄 간격", self.line_spacing),
            ("정렬", self.alignment),
            ("수평 앵커", self.horizontal_anchor),
            ("수직 앵커", self.vertical_anchor),
            ("Key Color", self.key_color),
        )
        for label, form_widget in rows:
            form.addRow(label, form_widget)
        scroll.setWidget(form_host)
        root.addWidget(scroll, 2)

        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color:#b45309;font-weight:700;")
        root.addWidget(self.warning)
        self.preview = OutputSurface(coordinator)
        root.addWidget(AspectRatioContainer(self.preview), 1)
        self.preview.set_content(
            Content.subtitle(
                "주님의 이름으로 환영합니다.\n함께 예배드리겠습니다.",
                0,
                style,
                key_color,
            )
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("Preview 적용")
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._preview)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        load_button.clicked.connect(self._load)
        save_button.clicked.connect(self._overwrite)
        new_button.clicked.connect(self._new)
        rename_button.clicked.connect(self._rename)
        delete_button.clicked.connect(self._delete)
        default_button.clicked.connect(self._set_default)

    @staticmethod
    def _double(
        minimum: float,
        maximum: float,
        value: float,
        step: float,
    ) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(2)
        widget.setSingleStep(step)
        widget.setValue(value)
        return widget

    @staticmethod
    def _enum_combo(enum_type: type[StrEnum], current: StrEnum) -> QComboBox:
        combo = QComboBox()
        for value in enum_type:
            combo.addItem(value.value.title(), value)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        return combo

    def _populate_presets(self, selected: str) -> None:
        self.preset_combo.clear()
        for name in self.presets:
            marker = " ★" if name == self.default_preset else ""
            self.preset_combo.addItem(name + marker, name)
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(selected)))

    def _style(self) -> SubtitleStyle:
        return SubtitleStyle(
            font_family=self.font_combo.currentFont().family(),
            font_size=self.font_size.value(),
            text_color=self.text_color.color,
            bold=self.bold.isChecked(),
            outline_color=self.outline_color.color,
            outline_width=self.outline_width.value(),
            shadow_color=self.shadow_color.color,
            shadow_opacity=self.shadow_opacity.value(),
            shadow_offset_x=self.shadow_x.value(),
            shadow_offset_y=self.shadow_y.value(),
            background_color=self.background_color.color,
            background_opacity=self.background_opacity.value(),
            background_padding=self.background_padding.value(),
            x_ratio=self.x_ratio.value(),
            y_ratio=self.y_ratio.value(),
            max_width_ratio=self.max_width.value(),
            line_spacing=self.line_spacing.value(),
            alignment=TextAlignment(self.alignment.currentData()),
            horizontal_anchor=HorizontalAnchor(self.horizontal_anchor.currentData()),
            vertical_anchor=VerticalAnchor(self.vertical_anchor.currentData()),
        )

    def _set_controls(self, style: SubtitleStyle) -> None:
        self.font_combo.setCurrentFont(QFont(style.font_family))
        self.font_size.setValue(style.font_size)
        self.text_color.set_color(style.text_color)
        self.bold.setChecked(style.bold)
        self.outline_color.set_color(style.outline_color)
        self.outline_width.setValue(style.outline_width)
        self.shadow_color.set_color(style.shadow_color)
        self.shadow_opacity.setValue(style.shadow_opacity)
        self.shadow_x.setValue(style.shadow_offset_x)
        self.shadow_y.setValue(style.shadow_offset_y)
        self.background_color.set_color(style.background_color)
        self.background_opacity.setValue(style.background_opacity)
        self.background_padding.setValue(style.background_padding)
        self.x_ratio.setValue(style.x_ratio)
        self.y_ratio.setValue(style.y_ratio)
        self.max_width.setValue(style.max_width_ratio)
        self.line_spacing.setValue(style.line_spacing)
        self.alignment.setCurrentIndex(self.alignment.findData(style.alignment))
        self.horizontal_anchor.setCurrentIndex(
            self.horizontal_anchor.findData(style.horizontal_anchor)
        )
        self.vertical_anchor.setCurrentIndex(self.vertical_anchor.findData(style.vertical_anchor))

    def _preview(self) -> None:
        style = self._style()
        key = self.key_color.color
        conflicts = conflicting_colors(style, key)
        self.warning.setText(
            "Key Color와 너무 유사한 색상: " + ", ".join(conflicts) if conflicts else ""
        )
        self.preview.set_content(
            Content.subtitle("주님의 이름으로 환영합니다.\n함께 예배드리겠습니다.", 0, style, key)
        )

    def _load(self) -> None:
        name = self.preset_combo.currentData()
        if name in self.presets:
            self._set_controls(self.presets[name])
            self._preview()

    def _overwrite(self) -> None:
        name = self.preset_combo.currentData()
        if name:
            self.presets[name] = self._style()
            self.settings_service.save_presets(self.presets, self.default_preset)

    def _new(self) -> None:
        name, accepted = QInputDialog.getText(self, "새 프리셋", "프리셋 이름")
        name = name.strip()
        if not accepted or not name:
            return
        if name in self.presets:
            QMessageBox.warning(self, "프리셋", "같은 이름의 프리셋이 있습니다.")
            return
        self.presets[name] = self._style()
        self.settings_service.save_presets(self.presets, self.default_preset)
        self._populate_presets(name)

    def _rename(self) -> None:
        old = self.preset_combo.currentData()
        new, accepted = QInputDialog.getText(self, "이름 변경", "새 이름", text=old)
        new = new.strip()
        if not accepted or not new or new == old:
            return
        if new in self.presets:
            QMessageBox.warning(self, "프리셋", "같은 이름의 프리셋이 있습니다.")
            return
        self.presets[new] = self.presets.pop(old)
        if self.default_preset == old:
            self.default_preset = new
        self.settings_service.save_presets(self.presets, self.default_preset)
        self._populate_presets(new)

    def _delete(self) -> None:
        name = self.preset_combo.currentData()
        if len(self.presets) <= 1:
            QMessageBox.warning(self, "프리셋", "마지막 프리셋은 삭제할 수 없습니다.")
            return
        del self.presets[name]
        if self.default_preset == name:
            self.default_preset = next(iter(self.presets))
        self.settings_service.save_presets(self.presets, self.default_preset)
        self._populate_presets(self.default_preset)

    def _set_default(self) -> None:
        self.default_preset = self.preset_combo.currentData()
        self.settings_service.save_presets(self.presets, self.default_preset)
        self._populate_presets(self.default_preset)

    def _accept(self) -> None:
        self.result_style = self._style()
        self.result_key_color = self.key_color.color
        self.result_preset = self.preset_combo.currentData()
        self._preview()
        self.accept()


def conflicting_colors(style: SubtitleStyle, key_color: str, threshold: int = 70) -> list[str]:
    """Return style color roles that are too close to the chroma key."""
    key = QColor(key_color)
    key_rgb = (key.red(), key.green(), key.blue())
    values = {
        "글자": QColor(style.text_color),
        "외곽선": QColor(style.outline_color),
        "그림자": QColor(style.shadow_color),
        "배경": QColor(style.background_color),
    }
    conflicts = []
    for name, color in values.items():
        color_rgb = (color.red(), color.green(), color.blue())
        distance = (
            sum((left - right) ** 2 for left, right in zip(key_rgb, color_rgb, strict=True)) ** 0.5
        )
        if distance < threshold:
            conflicts.append(name)
    return conflicts
