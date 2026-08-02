"""Списки «имя (подробности)»: в конфиг обязано уходить имя, а не ярлык.

Регрессия v0.24.1: пересборка списка мониторов сохраняла в cfg.output ярлык
целиком («HDMI-A-1 (1920x1080)»), и захват такого монитора не находил.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from adalight.gui.main_window import combo_value, select_combo_value  # noqa: E402

MONITORS = [("", "(основной)"), ("eDP-1", "eDP-1 (2560x1600)"),
            ("HDMI-A-1", "HDMI-A-1 (1920x1080)")]


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _combo() -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    for value, label in MONITORS:
        combo.addItem(label, value)
    return combo


def test_picked_item_gives_name(qt_app):
    combo = _combo()
    combo.setCurrentIndex(2)
    assert combo_value(combo) == "HDMI-A-1"


def test_survives_list_refresh(qt_app):
    """Пересборка списка (кнопка «обновить») не должна подменять имя ярлыком."""
    combo = _combo()
    combo.setCurrentIndex(2)

    current = combo_value(combo)
    combo.clear()
    for value, label in MONITORS:
        combo.addItem(label, value)
    select_combo_value(combo, current)

    assert combo_value(combo) == "HDMI-A-1"


def test_label_in_old_config_maps_back_to_name(qt_app):
    combo = _combo()
    select_combo_value(combo, "HDMI-A-1 (1920x1080)")
    assert combo_value(combo) == "HDMI-A-1"


def test_hand_typed_value_kept(qt_app):
    combo = _combo()
    combo.setEditText("DP-3")  # монитора нет в списке — оставляем как вписали
    assert combo_value(combo) == "DP-3"


def test_default_item_gives_empty_value(qt_app):
    combo = _combo()
    combo.setCurrentIndex(0)
    assert combo_value(combo) == ""
