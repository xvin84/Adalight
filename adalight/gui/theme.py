"""Темы оформления: тёмная / светлая (Fusion + QSS-дизайн-система) / системная.

Дизайн строится из токенов (фон, карточка, границы, акцент), общих для обеих
тем — QSS генерируется из одного шаблона, поэтому темы не расходятся.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES = ("dark", "light", "system")

ACCENT = "#6c8cff"

_DARK = {
    "bg": "#202225",
    "card": "#26282c",
    "input": "#1b1d20",
    "border": "#34373d",
    "hover": "#3d4148",
    "pressed": "#2a2c30",
    "text": "#e4e4e7",
    "text_dim": "#9a9da3",
    "title": "#9db1ff",
    "handle": "#e4e4e7",
}

_LIGHT = {
    "bg": "#f2f3f5",
    "card": "#ffffff",
    "input": "#ffffff",
    "border": "#d7dae0",
    "hover": "#e8eaef",
    "pressed": "#dde0e6",
    "text": "#1f2328",
    "text_dim": "#6a6f78",
    "title": "#4a63c8",
    "handle": "#ffffff",
}

_orig_style: str | None = None
_orig_palette: QPalette | None = None


def _build_qss(t: dict) -> str:
    return f"""
QMainWindow, QDialog {{ background: {t["bg"]}; }}
QWidget {{ font-size: 13px; }}
QToolTip {{
    background: {t["card"]}; color: {t["text"]};
    border: 1px solid {t["border"]}; border-radius: 6px; padding: 5px 8px;
}}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; color: {t["text_dim"]};
    padding: 7px 14px; margin: 2px; border-radius: 6px;
}}
QTabBar::tab:selected {{ background: {t["hover"]}; color: {t["text"]}; font-weight: 600; }}
QTabBar::tab:hover:!selected {{ background: {t["card"]}; }}

QGroupBox {{
    background: {t["card"]}; border: 1px solid {t["border"]};
    border-radius: 10px; margin-top: 14px; padding: 12px 8px 8px 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 10px; padding: 0 5px;
    color: {t["title"]}; font-weight: 600;
}}

QPushButton {{
    background: {t["hover"]}; border: 1px solid {t["border"]};
    border-radius: 6px; padding: 6px 12px; min-height: 16px;
}}
QPushButton:hover {{ background: {t["border"]}; }}
QPushButton:pressed {{ background: {t["pressed"]}; }}
QPushButton:disabled {{ color: {t["text_dim"]}; background: transparent; }}
QPushButton:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}

QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QTimeEdit {{
    background: {t["input"]}; border: 1px solid {t["border"]};
    border-radius: 6px; padding: 4px 8px; min-height: 18px;
    selection-background-color: {ACCENT};
}}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QLineEdit:focus, QTimeEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {t["card"]}; border: 1px solid {t["border"]};
    border-radius: 8px; selection-background-color: {t["hover"]};
}}

QSlider::groove:horizontal {{
    height: 4px; background: {t["border"]}; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 14px; height: 14px; margin: -6px 0;
    border-radius: 8px; background: {t["handle"]}; border: 1px solid {t["border"]};
}}
QSlider::handle:horizontal:hover {{ background: {ACCENT}; }}

QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {t["border"]}; background: {t["input"]};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QTableWidget {{
    background: {t["input"]}; border: 1px solid {t["border"]};
    border-radius: 8px; gridline-color: {t["border"]};
}}
QHeaderView::section {{
    background: {t["card"]}; color: {t["text_dim"]};
    border: none; padding: 5px; font-weight: 600;
}}
QTableWidget::item:selected {{ background: {t["hover"]}; color: {t["text"]}; }}

QScrollArea {{ background: transparent; }}
QScrollBar:vertical {{ width: 10px; background: transparent; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {t["hover"]}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {t["border"]}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {t["hover"]}; border-radius: 4px; min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QStatusBar {{ background: {t["input"]}; color: {t["text_dim"]}; }}
QStatusBar::item {{ border: none; }}

QMenu {{
    background: {t["card"]}; border: 1px solid {t["border"]};
    border-radius: 8px; padding: 4px;
}}
QMenu::item {{ padding: 6px 20px; border-radius: 5px; }}
QMenu::item:selected {{ background: {t["hover"]}; }}
QMenu::separator {{ height: 1px; background: {t["border"]}; margin: 4px 8px; }}
"""


def _dark_palette() -> QPalette:
    p = QPalette()
    window = QColor(_DARK["bg"])
    base = QColor(_DARK["input"])
    text = QColor(_DARK["text"])
    disabled = QColor(_DARK["text_dim"])

    p.setColor(QPalette.ColorRole.Window, window)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, base)
    p.setColor(QPalette.ColorRole.AlternateBase, window)
    p.setColor(QPalette.ColorRole.ToolTipBase, base)
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, window)
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.BrightText, QColor(255, 92, 92))
    p.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    p.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return p


def apply_theme(app: QApplication, theme: str) -> None:
    """Применяет тему на лету; «системная» возвращает исходный вид приложения."""
    global _orig_style, _orig_palette
    if _orig_style is None:
        _orig_style = app.style().objectName()
        _orig_palette = QPalette(app.palette())

    if theme == "dark":
        app.setStyle("Fusion")
        app.setPalette(_dark_palette())
        app.setStyleSheet(_build_qss(_DARK))
    elif theme == "light":
        app.setStyle("Fusion")
        app.setPalette(app.style().standardPalette())
        app.setStyleSheet(_build_qss(_LIGHT))
    else:
        app.setStyle(_orig_style)
        app.setPalette(_orig_palette)
        app.setStyleSheet("")
