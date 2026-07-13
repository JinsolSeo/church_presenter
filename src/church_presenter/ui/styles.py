from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_application_style(application: QApplication) -> None:
    """Apply a restrained broadcast-control visual theme."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#F1F5F9"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#172033"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#EAF0F6"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#172033"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#172033"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#2563EB"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#FFFFFF"))
    application.setPalette(palette)
    application.setStyleSheet(
        """
        QWidget { font-size: 13px; color: #172033; background-color: #f8fafc; }
        QLabel, QCheckBox { color: #172033; background-color: transparent; }
        QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget {
            background-color: #eef2f7;
        }
        QFrame#PreviewMonitor, QFrame#LiveMonitor {
            background-color: #ffffff; border: 2px solid #94a3b8; border-radius: 7px;
        }
        QFrame#PreviewMonitor { border-color: #2563eb; }
        QFrame#LiveMonitor { border-color: #dc2626; }
        QFrame#SyncControl {
            background-color: #e0f2fe; border: 1px solid #0284c7; border-radius: 7px;
        }
        QFrame#SyncControl[keyboardActive="true"] {
            background-color: #bae6fd; border: 3px solid #075985;
        }
        QCheckBox#SyncContentCheck {
            color: #0f172a; background-color: #ffffff; border: 2px solid #475569;
            border-radius: 5px; padding: 6px 10px; font-weight: 800;
        }
        QCheckBox#SyncContentCheck:checked {
            color: #ffffff; background-color: #1d4ed8; border-color: #1e3a8a;
        }
        QCheckBox#SyncContentCheck::indicator {
            width: 18px; height: 18px; background-color: #ffffff;
            border: 2px solid #334155; border-radius: 3px;
        }
        QCheckBox#SyncContentCheck::indicator:checked {
            background-color: #facc15; border: 3px solid #ffffff;
        }
        QPushButton {
            color: #172033; background-color: #ffffff; padding: 6px 10px;
            border: 1px solid #94a3b8; border-radius: 5px;
        }
        QPushButton:hover { color: #0f172a; background-color: #e2e8f0; }
        QPushButton:pressed { color: #ffffff; background-color: #475569; }
        QPushButton:checked { color: #ffffff; background-color: #2563eb; }
        QPushButton:disabled { color: #64748b; background-color: #e5e7eb; }
        QPushButton#DangerButton {
            color: #ffffff; background-color: #dc2626; border-color: #b91c1c;
            font-weight: 800; padding: 8px 14px;
        }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
            color: #172033; background-color: #ffffff; selection-color: #ffffff;
            selection-background-color: #2563eb; padding: 5px;
            border: 1px solid #94a3b8; border-radius: 4px;
        }
        QComboBox QAbstractItemView {
            color: #172033; background-color: #ffffff;
            selection-color: #ffffff; selection-background-color: #2563eb;
        }
        QTabWidget::pane { border: 1px solid #94a3b8; background-color: #ffffff; }
        QTabBar::tab { color: #334155; padding: 8px 20px; background-color: #dbe3ee; }
        QTabBar::tab:selected { color: #172033; background-color: #ffffff; font-weight: 700; }
        QListWidget {
            color: #172033; background-color: #ffffff; alternate-background-color: #edf2f7;
            selection-color: #ffffff; selection-background-color: #2563eb;
            border: 1px solid #cbd5e1;
        }
        QToolTip {
            color: #ffffff; background-color: #111827; border: 1px solid #64748b;
        }
        """
    )
