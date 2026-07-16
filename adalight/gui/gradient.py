"""Редактор градиента: произвольное число цветовых точек с позициями."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QColorDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

MIN_STOPS = 2
MAX_STOPS = 8


class _GradientBar(QWidget):
    """Полоска предпросмотра градиента."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(18)
        self._stops: list[tuple[float, str]] = []

    def set_stops(self, stops: list[tuple[float, str]]) -> None:
        self._stops = sorted(stops)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        grad = QLinearGradient(0, 0, self.width(), 0)
        for pos, color in self._stops:
            grad.setColorAt(min(max(pos, 0.0), 1.0), QColor(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(self.rect(), 4, 4)


class GradientEditor(QWidget):
    """Список точек «позиция + цвет» с добавлением/удалением и предпросмотром."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._loading = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self._bar = _GradientBar()
        root.addWidget(self._bar)
        self._rows_host = QVBoxLayout()
        self._rows_host.setContentsMargins(0, 0, 0, 0)
        root.addLayout(self._rows_host)
        self._btn_add = QPushButton("+ Добавить цвет")
        self._btn_add.clicked.connect(self._on_add)
        root.addWidget(self._btn_add)
        self._rows: list[QWidget] = []

    # ── данные ────────────────────────────────────────────────────────────

    def set_stops(self, stops: list[dict]) -> None:
        self._loading = True
        for row in self._rows:
            row.setParent(None)
        self._rows.clear()
        for stop in stops:
            self._add_row(float(stop["pos"]), str(stop["color"]))
        self._loading = False
        self._refresh()

    def stops(self) -> list[dict]:
        out = []
        for row in self._rows:
            btn: QPushButton = row.property("color_btn")
            spin: QDoubleSpinBox = row.property("pos_spin")
            out.append({"pos": round(spin.value(), 3), "color": btn.property("color_value")})
        return out

    # ── строки ────────────────────────────────────────────────────────────

    def _add_row(self, pos: float, color: str) -> None:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)

        btn = QPushButton()
        btn.setFixedSize(52, 22)
        self._set_color(btn, color)
        btn.clicked.connect(lambda: self._pick_color(btn))

        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1.0)
        spin.setSingleStep(0.05)
        spin.setDecimals(2)
        spin.setValue(pos)
        spin.setToolTip("Позиция точки вдоль ленты: 0 — начало, 1 — конец")
        spin.valueChanged.connect(self._on_changed)

        remove = QPushButton("✕")
        remove.setFixedWidth(28)
        remove.setToolTip("Удалить точку")
        remove.clicked.connect(lambda: self._remove_row(row))

        lay.addWidget(btn)
        lay.addWidget(spin, 1)
        lay.addWidget(remove)
        row.setProperty("color_btn", btn)
        row.setProperty("pos_spin", spin)
        self._rows.append(row)
        self._rows_host.addWidget(row)

    def _remove_row(self, row: QWidget) -> None:
        if len(self._rows) <= MIN_STOPS:
            return
        self._rows.remove(row)
        row.setParent(None)
        self._on_changed()

    def _on_add(self) -> None:
        if len(self._rows) >= MAX_STOPS:
            return
        self._add_row(1.0, "#ffffff")
        self._on_changed()

    # ── внутреннее ────────────────────────────────────────────────────────

    @staticmethod
    def _set_color(btn: QPushButton, value: str) -> None:
        btn.setProperty("color_value", value)
        btn.setStyleSheet(f"background: {value}; border: 1px solid #777; border-radius: 4px;")

    def _pick_color(self, btn: QPushButton) -> None:
        color = QColorDialog.getColor(QColor(btn.property("color_value")), self, "Цвет точки")
        if color.isValid():
            self._set_color(btn, color.name())
            self._on_changed()

    def _on_changed(self, *args) -> None:
        if self._loading:
            return
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        self._bar.set_stops([(s["pos"], s["color"]) for s in self.stops()])
        for row in self._rows:
            can_remove = len(self._rows) > MIN_STOPS
            row.layout().itemAt(2).widget().setEnabled(can_remove)
        self._btn_add.setEnabled(len(self._rows) < MAX_STOPS)
