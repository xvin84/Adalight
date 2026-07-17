"""API, который Adalight отдаёт плагинам.

Все методы потокобезопасны — плагины обычно работают в своих потоках.
"""

from __future__ import annotations

from collections.abc import Callable


class PluginAPI:
    def __init__(
        self,
        flash: Callable[[str, float, float, float, float], None],
        notify: Callable[[str, str], None],
        log: Callable[[str], None] | None = None,
    ):
        self._flash = flash
        self._notify = notify
        self._log = log or (lambda message: None)

    def trigger_flash(
        self,
        color: str,
        x: float,
        y: float,
        radius: float = 0.25,
        duration: float = 1.5,
    ) -> None:
        """Вспышка цветом «#rrggbb» в точке (x, y) экрана (0..1), поверх любого режима.

        Если подсветка выключена — вспышка молча игнорируется.
        """
        self._flash(color, x, y, radius, duration)

    def notify(self, title: str, text: str) -> None:
        """Системное уведомление из трея (уважает настройку «Уведомления в трее»)."""
        self._notify(title, text)

    def log(self, message: str) -> None:
        """Строка в лог приложения (для отладки плагина)."""
        self._log(message)
