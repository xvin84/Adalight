"""Пример плагина-эффекта: добавляет в лампу эффект «Плазма».

Показывает, как плагин расширяет НАБОР эффектов, а не только шлёт вспышки:
метод register(api) вызывается один раз при загрузке, и эффект появляется
в списке эффектов лампы наравне со встроенными. «Всё есть мод.»

Как установить:
1. Скопируйте файл в папку плагинов («Открыть папку плагинов» в менеджере).
2. Перезапустите Adalight (или поставьте из каталога — появится сразу).
3. Режим «Лампа» → эффект «Плазма».

Контракт эффекта:
- register(api) вызывается при загрузке плагина;
- api.register_lamp_effect(id, label, render, wants_color=…, wants_speed=…)
  добавляет эффект; render(cfg_like, n, t, points) -> RGB (n, 3) в 0..255:
  cfg_like — словарь настроек лампы (lamp_color/lamp_speed/…), n — число
  диодов, t — секунды, points — раскладка (side, x, y).
"""

from __future__ import annotations

import numpy as np


def _plasma(cfg_like: dict, n: int, t: float, points=None) -> np.ndarray:
    """Переливающиеся волны цвета: три несоизмеримых синуса на R/G/B."""
    speed = float(cfg_like.get("lamp_speed", 0.5))
    tt = t * (0.4 + speed * 1.2)
    x = np.linspace(0.0, 1.0, n)
    r = 0.5 + 0.5 * np.sin(2.0 * np.pi * (x * 2.0 + tt * 0.50))
    g = 0.5 + 0.5 * np.sin(2.0 * np.pi * (x * 3.0 - tt * 0.37 + 0.33))
    b = 0.5 + 0.5 * np.sin(2.0 * np.pi * (x * 1.5 + tt * 0.21 + 0.66))
    return np.stack([r, g, b], axis=1) * 255.0


class PlasmaPlugin:
    name = "plasma_effect"
    title = "Эффект «Плазма» (пример)"
    description = (
        "Добавляет в лампу эффект «Плазма» — переливающиеся волны цвета. "
        "Пример плагина, расширяющего набор эффектов."
    )
    version = "1.0"

    def register(self, api) -> None:
        """Вызывается при загрузке — регистрируем эффект в общем реестре."""
        api.register_lamp_effect("plasma", "Плазма", _plasma, wants_speed=True)

    def start(self, api, settings: dict) -> None:
        pass  # эффект работает и без включения — он часть набора эффектов

    def stop(self) -> None:
        pass


def create_plugin() -> PlasmaPlugin:
    return PlasmaPlugin()
