"""Автоматическая форма настроек плагина по его settings_schema.

Плагин объявляет схему (список полей-словарей) — менеджер строит форму без
кода GUI в самом плагине. Поддерживаемые типы: bool/int/float/choice/color/
text/note (см. base.SCHEMA_FIELD_TYPES).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from ..i18n import tr


class _ColorButton(QPushButton):
    """Кнопка-плашка цвета: хранит «#rrggbb», клик открывает палитру."""

    changed = Signal()

    def __init__(self, value: str = "#6c8cff") -> None:
        super().__init__()
        self.setFixedWidth(72)
        self.clicked.connect(self._pick)
        self.set_value(value)

    def set_value(self, value: str) -> None:
        self._value = value
        self.setStyleSheet(
            f"background:{value}; border:1px solid rgba(255,255,255,0.25);"
            "border-radius:6px; min-height:22px;"
        )

    def value(self) -> str:
        return self._value

    def _pick(self) -> None:
        color = QColorDialog.getColor(QColor(self._value), self, tr("Цвет"))
        if color.isValid():
            self.set_value(color.name())
            self.changed.emit()


class SettingsForm(QWidget):
    """Форма по схеме. values()/set_values() работают ключами схемы."""

    changed = Signal()

    def __init__(self, schema: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._schema = schema
        self._widgets: dict[str, object] = {}
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        for field in schema:
            ftype = field.get("type")
            if ftype == "note":
                note = QLabel(field.get("label", ""))
                note.setWordWrap(True)
                note.setObjectName("hintLabel")
                form.addRow(note)
                continue
            key = field.get("key")
            if not key:
                continue
            widget = self._make_widget(field)
            self._widgets[key] = widget
            form.addRow(field.get("label", key) + ":", widget)

    def _make_widget(self, field: dict) -> QWidget:
        ftype = field["type"]
        if ftype == "bool":
            w = QCheckBox()
            w.toggled.connect(self.changed)
            return w
        if ftype == "int":
            w = QSpinBox()
            w.setRange(int(field.get("min", 0)), int(field.get("max", 1000)))
            w.setSingleStep(int(field.get("step", 1)))
            w.valueChanged.connect(self.changed)
            return w
        if ftype == "float":
            w = QDoubleSpinBox()
            w.setRange(float(field.get("min", 0.0)), float(field.get("max", 1.0)))
            w.setSingleStep(float(field.get("step", 0.05)))
            w.valueChanged.connect(self.changed)
            return w
        if ftype == "choice":
            w = QComboBox()
            for choice in field.get("choices", []):
                val, label = choice if isinstance(choice, (list, tuple)) else (choice, choice)
                w.addItem(str(label), val)
            w.currentIndexChanged.connect(self.changed)
            return w
        if ftype == "color":
            w = _ColorButton(str(field.get("default", "#6c8cff")))
            w.changed.connect(self.changed)
            return w
        w = QLineEdit()  # text
        w.textChanged.connect(self.changed)
        return w

    def set_values(self, values: dict) -> None:
        for field in self._schema:
            key = field.get("key")
            if not key or key not in self._widgets:
                continue
            val = values.get(key, field.get("default"))
            w = self._widgets[key]
            if isinstance(w, QCheckBox):
                w.setChecked(bool(val))
            elif isinstance(w, QSpinBox):
                w.setValue(int(val))
            elif isinstance(w, QDoubleSpinBox):
                w.setValue(float(val))
            elif isinstance(w, QComboBox):
                idx = w.findData(val)
                w.setCurrentIndex(idx if idx >= 0 else 0)
            elif isinstance(w, _ColorButton):
                w.set_value(str(val))
            elif isinstance(w, QLineEdit):
                w.setText(str(val))

    def values(self) -> dict:
        out: dict = {}
        for key, w in self._widgets.items():
            if isinstance(w, QCheckBox):
                out[key] = w.isChecked()
            elif isinstance(w, QSpinBox):
                out[key] = w.value()
            elif isinstance(w, QDoubleSpinBox):
                out[key] = round(w.value(), 4)
            elif isinstance(w, QComboBox):
                out[key] = w.currentData()
            elif isinstance(w, _ColorButton):
                out[key] = w.value()
            elif isinstance(w, QLineEdit):
                out[key] = w.text()
        return out

    def has_fields(self) -> bool:
        return bool(self._widgets)
