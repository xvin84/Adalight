"""Расписание яркости: правила «интервал времени -> яркость» + дефолт вне интервалов."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time as dtime


@dataclass(frozen=True)
class ScheduleRule:
    start: dtime
    end: dtime
    brightness: float


def parse_time(value: str) -> dtime:
    """'HH:MM' -> datetime.time; бросает ValueError на мусор."""
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Ожидается время в формате ЧЧ:ММ, получено {value!r}")
    return dtime(int(parts[0]), int(parts[1]))


def parse_rules(raw: list[dict]) -> list[ScheduleRule]:
    """Список dict'ов из конфига -> валидные правила; бросает ValueError с номером строки."""
    rules: list[ScheduleRule] = []
    for i, item in enumerate(raw, start=1):
        try:
            start = parse_time(str(item["start"]))
            end = parse_time(str(item["end"]))
            brightness = float(item["brightness"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"Строка расписания {i}: {e}") from e
        if not 0.0 <= brightness <= 2.0:
            raise ValueError(f"Строка расписания {i}: яркость должна быть в диапазоне 0..2")
        if start == end:
            raise ValueError(f"Строка расписания {i}: начало и конец совпадают")
        rules.append(ScheduleRule(start, end, brightness))
    return rules


def brightness_at(now: dtime, rules: list[ScheduleRule], default: float) -> float:
    """Яркость на момент времени. Интервалы полуоткрытые [start, end),
    интервал через полночь (22:00–06:00) поддерживается; побеждает первое совпадение."""
    for r in rules:
        if r.start < r.end:
            if r.start <= now < r.end:
                return r.brightness
        else:  # интервал через полночь
            if now >= r.start or now < r.end:
                return r.brightness
    return default
