"""Автоформа настроек мода: скрытые поля за галочкой «дополнительные».

Спрятан только вид: значение advanced-поля обязано попадать в values(), иначе
сохранение настроек затирало бы паспортные токи «Защиты питания».
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from adalight.gui.plugin_settings import SettingsForm  # noqa: E402

SCHEMA = [
    {"key": "budget_ma", "type": "int", "label": "Бюджет", "min": 0, "max": 1000,
     "default": 500},
    {"key": "channel_ma", "type": "float", "advanced": True, "label": "Ток канала",
     "min": 0.0, "max": 100.0, "default": 20.0},
    {"type": "note", "advanced": True, "label": "Паспортные значения ленты."},
]


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def form(qt_app):
    form = SettingsForm(SCHEMA)
    form.set_values({"budget_ma": 500, "channel_ma": 20.0})
    form.show()  # видимость строк считается только у показанного виджета
    return form


def test_advanced_rows_are_hidden_by_default(form):
    assert form._widgets["budget_ma"].isVisible()
    assert not form._widgets["channel_ma"].isVisible()


def test_toggle_reveals_advanced_rows(form):
    form.chk_advanced.setChecked(True)
    assert form._widgets["channel_ma"].isVisible()
    form.chk_advanced.setChecked(False)
    assert not form._widgets["channel_ma"].isVisible()


def test_hidden_values_still_returned(form):
    """Скрытое поле остаётся настройкой — иначе его значение потеряется."""
    assert form.values() == {"budget_ma": 500, "channel_ma": 20.0}


def test_form_without_advanced_has_no_toggle(qt_app):
    plain = SettingsForm([SCHEMA[0]])
    assert not hasattr(plain, "chk_advanced")
