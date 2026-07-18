"""Настройки плагина «Вспышки уведомлений» — самостоятельный виджет.

Богаче обычной формы по схеме: перетаскиваемый пикер позиции по периметру,
переключатель стиля вспышки, цвета и пробная вспышка. Менеджер плагинов
встраивает его вместо авто-формы.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

from .flash_picker import FlashPositionPicker
from .plugin_settings import _ColorButton


class NotificationSettingsWidget(QWidget):
    changed = Signal()
    flashTest = Signal()   # запросить пробную вспышку текущими значениями
    dragTest = Signal()    # пикер отпущен — вспышка, если подсветка работает

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)

        hint = QLabel(
            "Ловятся только <b>системные</b> уведомления. Если приложение рисует "
            "свои всплывашки — вспышки не будет: включите у него системные "
            "уведомления. Telegram: Настройки → Уведомления → «Использовать "
            "уведомления Windows». В Discord они системные по умолчанию."
        )
        hint.setWordWrap(True)
        hint.setObjectName("hintLabel")
        form.addRow(hint)

        self.picker = FlashPositionPicker()
        self.picker.changed.connect(self.changed)
        self.picker.released.connect(self.dragTest)
        form.addRow("Позиция:", self.picker)

        self.sl_radius = QSlider(Qt.Orientation.Horizontal)
        self.sl_radius.setRange(5, 60)
        lbl = QLabel()
        lbl.setFixedWidth(38)
        self.sl_radius.valueChanged.connect(lambda v: lbl.setText(f"{v / 100:.2f}"))
        self.sl_radius.valueChanged.connect(lambda v: self.picker.set_radius(v / 100))
        self.sl_radius.valueChanged.connect(self.changed)
        row = QHBoxLayout()
        row.addWidget(self.sl_radius, 1)
        row.addWidget(lbl)
        form.addRow("Радиус:", row)

        self.cb_style = QComboBox()
        self.cb_style.addItem("Бульк (волна)", "ripple")
        self.cb_style.addItem("Пятно", "blob")
        self.cb_style.setToolTip(
            "«Бульк» — яркая капля с расходящейся по ленте волной; «Пятно» — "
            "мягкая вспышка на месте."
        )
        self.cb_style.currentIndexChanged.connect(self.changed)
        form.addRow("Стиль:", self.cb_style)

        self.btn_telegram = _ColorButton("#4fc3f7")
        self.btn_telegram.changed.connect(self.changed)
        form.addRow("Telegram:", self.btn_telegram)
        self.btn_discord = _ColorButton("#7c4dff")
        self.btn_discord.changed.connect(self.changed)
        form.addRow("Discord:", self.btn_discord)

        self.ch_any = QCheckBox("Любые приложения — цвет от иконки")
        self.ch_any.setToolTip(
            "Вспыхивать на уведомления всех приложений: цвет берётся из иконки "
            "приложения (Telegram и Discord сохраняют свои цвета)."
        )
        self.ch_any.toggled.connect(self.changed)
        form.addRow(self.ch_any)

        btn_test = QPushButton("Тест вспышки")
        btn_test.setToolTip("Показать вспышку на ленте (подсветка должна работать)")
        btn_test.clicked.connect(self.flashTest)
        form.addRow(btn_test)

    def set_values(self, v: dict) -> None:
        self.picker.set_values(float(v["x"]), float(v["y"]), float(v["radius"]))
        self.sl_radius.setValue(round(float(v["radius"]) * 100))
        idx = self.cb_style.findData(v.get("flash_style", "ripple"))
        self.cb_style.setCurrentIndex(idx if idx >= 0 else 0)
        self.btn_telegram.set_value(v["telegram_color"])
        self.btn_discord.set_value(v["discord_color"])
        self.ch_any.setChecked(bool(v.get("any_app", False)))

    def values(self) -> dict:
        x, y = self.picker.values()
        return {
            "x": x,
            "y": y,
            "radius": self.sl_radius.value() / 100,
            "flash_style": self.cb_style.currentData(),
            "telegram_color": self.btn_telegram.value(),
            "discord_color": self.btn_discord.value(),
            "any_app": self.ch_any.isChecked(),
        }
