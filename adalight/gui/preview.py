"""Виджет предпросмотра: схема монитора, живые цвета диодов, картинка экрана
и зоны сбора цвета."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..config import Config
from ..geometry import LedGeometry
from ..i18n import tr

_MARGIN = 26
_SCREEN_BG = QColor(28, 30, 34)
_SCREEN_BORDER = QColor(90, 94, 102)
_LED_OFF = QColor(70, 72, 78)
_FIRST_LED_RING = QColor(255, 255, 255)
_ZONE_BORDER = QColor(0, 220, 255, 190)
_ZONE_FILL = QColor(0, 220, 255, 45)

# нормализация зон не зависит от реального разрешения, важна только пропорция
_REF_W, _REF_H = 1920, 1080


class LedPreview(QWidget):
    """Рамка «монитора» с диодами вокруг; внутри — кадр экрана и зоны захвата.

    Диоды кликабельны: клик испускает ledClicked(индекс) — главное окно
    вспыхивает этим диодом на реальной ленте.
    """

    ledClicked = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(320, 220)
        self.setMouseTracking(True)
        self._points: list[tuple[str, float, float]] = []
        self._zones: list[tuple[float, float, float, float]] = []  # x, y, w, h (доли)
        self._led_rects: list[QRectF] = []  # экранные прямоугольники диодов
        self._colors: np.ndarray | None = None
        self._frame: QImage | None = None
        self.show_screen = True
        self.show_zones = True

    def _led_at(self, pos) -> int:
        for i, rect in enumerate(self._led_rects):
            if rect.adjusted(-2, -2, 2, 2).contains(pos):
                return i
        return -1

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        index = self._led_at(event.position())
        if index >= 0:
            self.ledClicked.emit(index)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        hit = self._led_at(event.position()) >= 0
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if hit else Qt.CursorShape.ArrowCursor
        )
        if hit:
            self.setToolTip(
                tr("Диод {n} — клик, чтобы вспыхнуть им на ленте").format(
                    n=self._led_at(event.position()) + 1
                )
            )

    def set_config(self, cfg: Config) -> None:
        """Перестроить раскладку и зоны (вызывается при изменении настроек)."""
        try:
            geom = LedGeometry(cfg)
            self._points = geom.points
            self._zones = [
                (x1 / _REF_W, y1 / _REF_H, (x2 - x1) / _REF_W, (y2 - y1) / _REF_H)
                for (y1, y2, x1, x2) in geom.calculate_slices(_REF_W, _REF_H)
            ]
        except ValueError:
            self._points = []
            self._zones = []
        self._colors = None
        self.update()

    def set_colors(self, colors: np.ndarray) -> None:
        self._colors = colors
        self.update()

    def set_frame(self, frame: np.ndarray) -> None:
        """Уменьшенный RGB-кадр экрана из движка."""
        h, w = frame.shape[:2]
        self._frame = QImage(frame.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self.update()

    def clear_frame(self) -> None:
        self._frame = None
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

        if self.show_screen and self._frame is not None:
            inner = area.adjusted(2, 2, -2, -2)
            p.save()
            p.setClipRect(inner)
            p.drawImage(QRect(inner), self._frame)
            p.restore()

        if self.show_zones:
            p.setPen(QPen(_ZONE_BORDER, 1))
            p.setBrush(_ZONE_FILL)
            for x, y, w, h in self._zones:
                p.drawRect(
                    QRectF(
                        area.x() + x * area.width(),
                        area.y() + y * area.height(),
                        w * area.width(),
                        h * area.height(),
                    )
                )

        if not self._points:
            p.setPen(_SCREEN_BORDER)
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, tr("Нет диодов"))
            return

        max_side = max(
            sum(1 for s, _, _ in self._points if s == side)
            for side in ("top", "right", "bottom", "left")
        )
        size = max(4.0, min(14.0, area.width() / (max_side * 1.6)))
        offset = size * 0.75 + 3  # вынос диода за рамку

        self._led_rects = []
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
            self._led_rects.append(rect)
            if i == 0:
                p.setPen(QPen(_FIRST_LED_RING, 1.5))
            else:
                p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(rect, 2, 2)
