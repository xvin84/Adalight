"""Пример плагина Adalight: «Напоминание о перерыве».

Каждые N минут лента мягко вспыхивает зелёным — пора встать и размяться.

Как установить:
1. Скопируйте этот файл в папку плагинов:
   Windows: %APPDATA%\\adalight\\plugins\\
   Linux:   ~/.config/adalight/plugins/
   (кнопка «Открыть папку плагинов» на вкладке «Плагины» откроет её)
2. Перезапустите Adalight — плагин появится на вкладке «Плагины».
3. Включите его галочкой. Настройки можно менять в config.json в секции
   plugins -> break_reminder (например, "interval_min": 45).

Контракт плагина:
- модуль обязан содержать функцию create_plugin() -> объект плагина;
- у объекта: атрибуты name / title / description
  и методы start(api, settings) / stop();
- start() должен быстро вернуть управление — долгую работу ведите в своём
  потоке (как здесь);
- stop() обязан остановить все ваши потоки.

API (adalight.plugins.base.PluginAPI), все методы потокобезопасны:
- api.trigger_flash(color, x, y, radius=0.25, duration=1.5) — вспышка на ленте:
  color — "#rrggbb"; x, y — точка экрана в долях (0,0 — левый верх,
  1,1 — правый низ); только когда подсветка запущена;
- api.notify(title, text) — системное уведомление из трея;
- api.log(message) — строка в лог для отладки.
"""

from __future__ import annotations

import threading

DEFAULTS = {
    "enabled": False,
    "interval_min": 50,     # период напоминаний, минут
    "color": "#2ecc71",     # цвет вспышки
}


class BreakReminderPlugin:
    # имя — ключ в конфиге, латиницей без пробелов; title/description видны в GUI
    name = "break_reminder"
    title = "Напоминание о перерыве (пример)"
    description = (
        "Каждые N минут лента вспыхивает зелёным по центру экрана — "
        "напоминание встать и размяться. Пример пользовательского плагина."
    )

    def __init__(self) -> None:
        self._api = None
        self._settings: dict = dict(DEFAULTS)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, api, settings: dict) -> None:
        """Вызывается при включении плагина (и после смены настроек)."""
        self._api = api
        self._settings = {**DEFAULTS, **settings}
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Вызывается при выключении плагина и при выходе из программы."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def _run(self) -> None:
        interval_s = max(1.0, float(self._settings["interval_min"]) * 60.0)
        # Event.wait вместо time.sleep: мгновенная реакция на stop()
        while not self._stop.wait(interval_s):
            color = str(self._settings["color"])
            # три мягких волны по центру экрана
            self._api.trigger_flash(color, x=0.5, y=0.5, radius=0.6, duration=2.5)
            self._api.notify("Перерыв!", "Вы давно сидите — время размяться.")


def create_plugin() -> BreakReminderPlugin:
    return BreakReminderPlugin()
