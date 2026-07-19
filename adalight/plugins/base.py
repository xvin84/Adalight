"""API, который Adalight отдаёт плагинам.

Все методы потокобезопасны — плагины обычно работают в своих потоках.
"""

from __future__ import annotations

from collections.abc import Callable

# Типы полей в settings_schema плагина. Менеджер плагинов строит по схеме форму
# настроек автоматически — плагину не нужен код GUI.
SCHEMA_FIELD_TYPES = ("bool", "int", "float", "choice", "color", "text", "note")


def schema_defaults(schema: list[dict] | None) -> dict:
    """Значения по умолчанию из settings_schema (Qt-free, зовётся и в тестах)."""
    out: dict = {}
    for field in schema or []:
        key = field.get("key")
        if key and field.get("type") != "note" and "default" in field:
            out[key] = field["default"]
    return out


class PluginAPI:
    def __init__(
        self,
        flash: Callable[..., None],
        notify: Callable[[str, str], None],
        log: Callable[[str], None] | None = None,
        source: str = "",
    ):
        self._flash = flash
        self._notify = notify
        self._log = log or (lambda message: None)
        self._source = source  # имя мода — чтобы помечать его регистрации

    def bound(self, source: str) -> PluginAPI:
        """Копия API, помечающая регистрации именем мода (для снятия при выкл.)."""
        return PluginAPI(self._flash, self._notify, self._log, source)

    def trigger_flash(
        self,
        color: str,
        x: float,
        y: float,
        radius: float = 0.25,
        duration: float = 1.5,
        style: str = "ripple",
    ) -> None:
        """Вспышка цветом «#rrggbb» в точке (x, y) экрана (0..1), поверх любого режима.

        style="ripple" — «бульк» с расходящейся волной, style="blob" — статичное
        пятно. Если подсветка выключена — вспышка молча игнорируется.
        """
        self._flash(color, x, y, radius, duration, style)

    def register_lamp_effect(
        self,
        effect_id: str,
        label: str,
        render,
        *,
        wants_color: bool = False,
        wants_speed: bool = False,
        wants_gradient: bool = False,
        wants_fire: bool = False,
    ) -> None:
        """Добавить свой эффект лампы — он появится в списке эффектов наравне со
        встроенными («всё есть мод»).

        render(cfg_like, n, t, points) -> RGB-массив (n, 3) в 0..255: cfg_like —
        словарь настроек лампы (lamp_color/lamp_speed/…), n — число диодов,
        t — секунды, points — раскладка (side, x, y). Флаги wants_* подсказывают
        GUI, какие контролы показать: цвет, скорость, редактор градиента
        (cfg["lamp_gradient"]), настройки камина (cfg["fire_*"]).
        """
        from ..effects import register_lamp_effect

        register_lamp_effect(
            effect_id, label, render,
            wants_color=wants_color, wants_speed=wants_speed,
            wants_gradient=wants_gradient, wants_fire=wants_fire, source=self._source,
        )

    def notify(self, title: str, text: str) -> None:
        """Системное уведомление из трея (уважает настройку «Уведомления в трее»)."""
        self._notify(title, text)

    def log(self, message: str) -> None:
        """Строка в лог приложения (для отладки плагина)."""
        self._log(message)
