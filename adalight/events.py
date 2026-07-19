"""Событийная шина ядра: простой потокобезопасный pub/sub.

Ядро и моды эмитят события (`engine.started`, `notification.received`, …), а
моды/плагины подписываются, чтобы реагировать на состояние — не завися от
внутренностей друг друга. Каждая подписка помнит, **каким модом** сделана
(`source`), чтобы снять её при выключении мода — как в реестрах эффектов/
транспортов.

Полезная нагрузка события — словарь: `emit("engine.started", mode="lamp")`
доставит обработчику `handler({"mode": "lamp"})`. Словарь устойчив к появлению
новых полей — обработчик берёт что знает.

События ядра (имена — свободные строки, это лишь ориентир):
- `engine.started` {mode} / `engine.stopped` {mode} — движок начал/закончил цикл;
- `engine.frame` {colors} — кадр отправлен на ленту (эмитится только если есть
  подписчики — на горячем цикле иначе бесплатно);
- `notification.received` {app, color} — мод уведомлений увидел уведомление;
- `update.available` {version, url} — доступна новая версия.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

Handler = Callable[[dict], None]


class EventBus:
    """Потокобезопасный pub/sub. Исключение в обработчике не роняет emit."""

    def __init__(self) -> None:
        self._subs: dict[str, list[tuple[str, Handler]]] = {}
        self._lock = threading.Lock()

    def subscribe(
        self, event: str, handler: Handler, *, source: str = ""
    ) -> Callable[[], None]:
        """Подписаться на событие. Возвращает функцию отписки."""
        with self._lock:
            self._subs.setdefault(event, []).append((source, handler))

        def _off() -> None:
            with self._lock:
                lst = self._subs.get(event)
                if lst is not None:
                    self._subs[event] = [
                        pair for pair in lst if pair[1] is not handler
                    ]
                    if not self._subs[event]:
                        del self._subs[event]

        return _off

    def unsubscribe_source(self, source: str) -> None:
        """Снять все подписки мода source (при его выключении)."""
        with self._lock:
            for event in list(self._subs):
                self._subs[event] = [
                    pair for pair in self._subs[event] if pair[0] != source
                ]
                if not self._subs[event]:
                    del self._subs[event]

    def has_subscribers(self, event: str) -> bool:
        """Есть ли подписчики (чтобы не готовить нагрузку зря на горячем цикле)."""
        with self._lock:
            return bool(self._subs.get(event))

    def emit(self, event: str, **payload) -> None:
        """Разослать событие. Обработчики вызываются вне блокировки; ошибки в них
        изолируются — один битый подписчик не мешает остальным и эмитеру."""
        with self._lock:
            handlers = [h for _s, h in self._subs.get(event, ())]
        for handler in handlers:
            try:
                handler(dict(payload))
            except Exception:  # noqa: BLE001 — подписчик не должен ронять эмитера
                pass

    def clear(self) -> None:
        """Снять все подписки (для тестов/перезапуска)."""
        with self._lock:
            self._subs.clear()


# Общая шина приложения (как module-level реестры эффектов/транспортов).
_BUS = EventBus()


def bus() -> EventBus:
    return _BUS


def subscribe(event: str, handler: Handler, *, source: str = "") -> Callable[[], None]:
    return _BUS.subscribe(event, handler, source=source)


def unsubscribe_source(source: str) -> None:
    _BUS.unsubscribe_source(source)


def has_subscribers(event: str) -> bool:
    return _BUS.has_subscribers(event)


def emit(event: str, **payload) -> None:
    _BUS.emit(event, **payload)
