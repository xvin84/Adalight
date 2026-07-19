"""Пример плагина, использующего событийную шину.

Показывает, как мод РЕАГИРУЕТ на состояние приложения, ничего не зная о его
внутренностях: подписывается на события ядра и других модов. «Всё есть мод.»

Здесь плагин слушает уведомления (их эмитит встроенный мод «Вспышки
уведомлений») и запуск/остановку движка, и пишет их в лог приложения.

Как установить:
1. Скопируйте файл в папку плагинов («Открыть папку плагинов» в менеджере).
2. Перезапустите Adalight (или поставьте из каталога — появится сразу).
3. Включите мод в менеджере плагинов.

Контракт:
- register(api) вызывается при ВКЛЮЧЕНИИ мода;
- api.on(event, handler) подписывает handler(payload: dict) на событие; подписка
  снимается, когда мод выключают;
- api.emit(event, **data) рассылает своё событие (другие моды могут слушать).

События ядра: engine.started/stopped {mode}, engine.frame {colors},
notification.received {app, color}, update.available {version, url}.
"""

from __future__ import annotations


class NotificationLogger:
    name = "notification_logger"
    title = "Лог уведомлений (пример)"
    description = (
        "Пишет в лог приложения уведомления (от мода «Вспышки уведомлений») и "
        "старт/стоп подсветки. Пример плагина на событийной шине."
    )
    version = "1.0"

    def __init__(self) -> None:
        self._api = None

    def register(self, api) -> None:
        self._api = api
        api.on("notification.received", self._on_notification)
        api.on("engine.started", self._on_started)
        api.on("engine.stopped", self._on_stopped)

    def _on_notification(self, payload: dict) -> None:
        app = payload.get("app") or "приложение"
        color = payload.get("color", "")
        self._api.log(f"Уведомление от «{app}» → вспышка {color}")

    def _on_started(self, payload: dict) -> None:
        self._api.log(f"Подсветка запущена: режим {payload.get('mode')}")

    def _on_stopped(self, payload: dict) -> None:
        self._api.log(f"Подсветка остановлена: режим {payload.get('mode')}")


def create_plugin() -> NotificationLogger:
    return NotificationLogger()
