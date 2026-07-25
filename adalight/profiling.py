"""Профилирование цикла вывода по участкам: где кадр теряет время.

Включается переменной окружения ADALIGHT_PROFILE: «1» — отчёт каждые 120
кадров, любое другое число — свой период в кадрах. Отчёт уходит в stderr:
среднее время каждого участка в миллисекундах и достигнутый fps. Выключенный
профилировщик стоит один булев чек на вызов — им можно пользоваться
безусловно в горячем цикле.

Использование в цикле:

    prof = LoopProfiler.from_env()
    while ...:
        prof.begin()
        ...захват...
        prof.mark("захват")
        ...обработка...
        prof.mark("кадр")
        prof.frame()
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable

_DEFAULT_PERIOD = 120


class LoopProfiler:
    """Накапливает время между метками mark() и печатает среднее раз в N кадров."""

    def __init__(self, report_every: int = 0, sink: Callable[[str], None] | None = None):
        self.enabled = report_every > 0
        self._every = report_every
        self._sink = sink or (lambda line: print(line, file=sys.stderr, flush=True))
        self._sections: dict[str, float] = {}   # имя -> суммарные секунды за период
        self._frames = 0
        self._busy = 0.0                         # суммарное время begin()..frame()
        self._t_frame0 = 0.0
        self._t_prev = 0.0
        self._t_report = time.perf_counter()

    @classmethod
    def from_env(cls, var: str = "ADALIGHT_PROFILE") -> LoopProfiler:
        raw = os.environ.get(var, "").strip()
        if not raw or raw == "0":
            return cls(report_every=0)
        try:
            n = int(raw)
        except ValueError:
            n = 1
        return cls(report_every=n if n > 1 else _DEFAULT_PERIOD)

    def begin(self) -> None:
        """Начало итерации цикла."""
        if not self.enabled:
            return
        self._t_frame0 = self._t_prev = time.perf_counter()

    def mark(self, section: str) -> None:
        """Списать время с предыдущей метки (или begin) на участок section."""
        if not self.enabled:
            return
        now = time.perf_counter()
        self._sections[section] = self._sections.get(section, 0.0) + (now - self._t_prev)
        self._t_prev = now

    def frame(self) -> None:
        """Конец итерации; раз в N кадров — отчёт и сброс накопленного."""
        if not self.enabled:
            return
        now = time.perf_counter()
        self._busy += now - self._t_frame0
        self._frames += 1
        if self._frames < self._every:
            return
        wall = now - self._t_report
        fps = self._frames / wall if wall > 0 else 0.0
        per_frame = [
            f"{name} {1000.0 * total / self._frames:.2f}"
            for name, total in self._sections.items()
        ]
        other = self._busy - sum(self._sections.values())
        per_frame.append(f"прочее {1000.0 * other / self._frames:.2f}")
        self._sink(
            f"[профиль] {fps:6.1f} fps | "
            + " | ".join(per_frame)
            + f" (мс/кадр, среднее за {self._frames} кадров)"
        )
        self._sections.clear()
        self._frames = 0
        self._busy = 0.0
        self._t_report = now
