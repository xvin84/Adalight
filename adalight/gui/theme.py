"""Темы оформления: тёмная / светлая (Fusion) / системная."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES = ("dark", "light", "system")

_orig_style: str | None = None
_orig_palette: QPalette | None = None


def _dark_palette() -> QPalette:
    p = QPalette()
    window = QColor(45, 47, 51)
    base = QColor(32, 34, 37)
    text = QColor(228, 228, 231)
    disabled = QColor(128, 128, 132)
    highlight = QColor(53, 132, 228)

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
    p.setColor(QPalette.ColorRole.Link, QColor(88, 166, 255))
    p.setColor(QPalette.ColorRole.Highlight, highlight)
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
    elif theme == "light":
        app.setStyle("Fusion")
        app.setPalette(app.style().standardPalette())
    else:
        app.setStyle(_orig_style)
        app.setPalette(_orig_palette)
