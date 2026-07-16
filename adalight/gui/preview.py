"""Виджет предпросмотра: схема монитора с живыми цветами диодов."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..config import Config
from ..geometry import LedGeometry

_MARGIN = 26
_SCREEN_BG = QColor(28, 30, 34)
_SCREEN_BORDER = QColor(90, 94, 102)
_LED_OFF = QColor(70, 72, 78)
_FIRST_LED_RING = QColor(255, 255, 255)


class LedPreview(QWidget):
    """Рисует рамку «монитора» и диоды вокруг неё; первый диод помечен кольцом."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(320, 220)
        self._points: list[tuple[str, float, float]] = []
        self._colors: np.ndarray | None = None

    def set_config(self, cfg: Config) -> None:
        """Перестроить раскладку (вызывается при изменении настроек геометрии)."""
        try:
            self._points = LedGeometry(cfg).points
        except ValueError:
            self._points = []
        self._colors = None
        self.update()

    def set_colors(self, colors: np.ndarray) -> None:
        self._colors = colors
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        area = self.rect().adjusted(_MARGIN, _MARGIN, -_MARGIN, -_MARGIN)
        # держим пропорции 16:9
        if area.width() / max(area.height(), 1) > 16 / 9:
            w = int(area.height() * 16 / 9)
            area.setLeft(area.center().x() - w // 2)
            area.setWidth(w)
        else:
            h = int(area.width() * 9 / 16)
            area.setTop(area.center().y() - h // 2)
            area.setHeight(h)

        p.setPen(QPen(_SCREEN_BORDER, 1.5))
        p.setBrush(_SCREEN_BG)
        p.drawRoundedRect(area, 6, 6)

        if not self._points:
            p.setPen(_SCREEN_BORDER)
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, "Нет диодов")
            return

        max_side = max(
            sum(1 for s, _, _ in self._points if s == side)
            for side in ("top", "right", "bottom", "left")
        )
        size = max(4.0, min(14.0, area.width() / (max_side * 1.6)))
        offset = size * 0.75 + 3  # вынос диода за рамку

        for i, (side, x, y) in enumerate(self._points):
            cx = area.x() + x * area.width()
            cy = area.y() + y * area.height()
            if side == "top":
                cy = area.y() - offset
            elif side == "bottom":
                cy = area.bottom() + offset
            elif side == "left":
                cx = area.x() - offset
            else:
                cx = area.right() + offset

            if self._colors is not None and i < len(self._colors):
                r, g, b = (int(v) for v in self._colors[i])
                color = QColor(r, g, b)
            else:
                color = _LED_OFF

            rect = QRectF(cx - size / 2, cy - size / 2, size, size)
            if i == 0:
                p.setPen(QPen(_FIRST_LED_RING, 1.5))
            else:
                p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(rect, 2, 2)
