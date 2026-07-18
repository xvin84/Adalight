"""Виджет выбора позиции вспышки: перетащите пятно по схеме экрана."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

_SCREEN_BG = QColor(28, 30, 34)
_SCREEN_BORDER = QColor(90, 94, 102)
_GLOW = QColor(108, 140, 255)


def snap_to_perimeter(x: float, y: float) -> tuple[float, float]:
    """Проекция точки на ближайший край экрана: лента одномерна, центр не нужен."""
    x = min(max(x, 0.0), 1.0)
    y = min(max(y, 0.0), 1.0)
    edges = ((x, 0.0, y), (1.0 - x, 1.0, y), (y, x, 0.0), (1.0 - y, x, 1.0))
    _, nx, ny = min(edges, key=lambda e: e[0])
    return nx, ny


class FlashPositionPicker(QWidget):
    """Схема монитора; клик или перетаскивание ставит точку вспышки.

    changed — при каждом сдвиге (для сохранения настроек),
    released — когда отпустили мышь (удобно для пробной вспышки на ленте).
    """

    changed = Signal()
    released = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(130)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip("Перетащите пятно по краю экрана — туда, где вспыхнет лента")
        self._x, self._y = snap_to_perimeter(0.85, 0.9)
        self._radius = 0.3
        self._dragging = False

    # ── данные ────────────────────────────────────────────────────────────

    def set_values(self, x: float, y: float, radius: float) -> None:
        """Программная установка (без испускания changed)."""
        self._x, self._y = snap_to_perimeter(float(x), float(y))
        self._radius = float(radius)
        self.update()

    def set_radius(self, radius: float) -> None:
        self._radius = float(radius)
        self.update()

    def values(self) -> tuple[float, float]:
        return round(self._x, 2), round(self._y, 2)

    # ── мышь ──────────────────────────────────────────────────────────────

    def _apply_pos(self, event) -> None:
        rect = self._screen_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        x = (event.position().x() - rect.x()) / rect.width()
        y = (event.position().y() - rect.y()) / rect.height()
        self._x, self._y = snap_to_perimeter(x, y)
        self.update()
        self.changed.emit()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._dragging = True
        self._apply_pos(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._dragging:
            self._apply_pos(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self._dragging = False
        self.released.emit()

    # ── отрисовка ─────────────────────────────────────────────────────────

    def _screen_rect(self) -> QRectF:
        area = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        if area.width() / max(area.height(), 1) > 16 / 9:
            w = area.height() * 16 / 9
            return QRectF(area.center().x() - w / 2, area.y(), w, area.height())
        h = area.width() * 9 / 16
        return QRectF(area.x(), area.center().y() - h / 2, area.width(), h)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self._screen_rect()

        p.setPen(QPen(_SCREEN_BORDER, 1.5))
        p.setBrush(_SCREEN_BG)
        p.drawRoundedRect(rect, 6, 6)

        cx = rect.x() + self._x * rect.width()
        cy = rect.y() + self._y * rect.height()
        glow_r = max(self._radius * rect.width(), 8.0)

        p.setClipRect(rect.adjusted(1, 1, -1, -1))
        grad = QRadialGradient(cx, cy, glow_r)
        grad.setColorAt(0.0, QColor(_GLOW.red(), _GLOW.green(), _GLOW.blue(), 200))
        grad.setColorAt(1.0, QColor(_GLOW.red(), _GLOW.green(), _GLOW.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawEllipse(QRectF(cx - glow_r, cy - glow_r, glow_r * 2, glow_r * 2))
        p.setClipping(False)

        p.setPen(QPen(QColor(255, 255, 255), 1.5))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QRectF(cx - 3, cy - 3, 6, 6))
