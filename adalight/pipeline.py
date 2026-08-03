"""Реестр фильтров кадра: последняя обработка перед отправкой на ленту.

Фильтр получает готовые RGB-байты (N, 3) — ровно те, что уйдут в ленту, уже
после насыщенности, температуры, гаммы, яркости и вспышек, — и возвращает
изменённые. Так мод влияет на сам вывод, не трогая ядро: на этом держится
«Защита питания», которая считает ток по кадру и притушивает ленту.

Фильтры применяются во всех режимах движка (включая тесты «стороны» и
«бегущая точка» — они как раз жгут полную яркость) в порядке priority: меньше
— раньше. Ошибка фильтра не роняет вывод: битый фильтр пропускается, кадр
идёт дальше как есть.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

FrameFilter = Callable[[np.ndarray], "np.ndarray | None"]


@dataclass
class FrameFilterSpec:
    id: str
    fn: FrameFilter
    priority: int = 50  # меньше — раньше в цепочке
    source: str = ""    # имя мода, зарегистрировавшего фильтр (для снятия)


_FILTERS: dict[str, FrameFilterSpec] = {}
# Отсортированный снимок реестра: цепочка перебирается на каждом кадре, а
# меняется редко — сортировать в горячем цикле незачем. Кортеж целиком
# заменяется, поэтому поток движка всегда видит согласованный список.
_ORDER: tuple[FrameFilterSpec, ...] = ()


def _rebuild() -> None:
    global _ORDER
    _ORDER = tuple(sorted(_FILTERS.values(), key=lambda s: (s.priority, s.id)))


def register_frame_filter(
    filter_id: str, fn: FrameFilter, *, priority: int = 50, source: str = ""
) -> None:
    """Добавить фильтр кадра в реестр (повторный id — перезапись)."""
    _FILTERS[filter_id] = FrameFilterSpec(filter_id, fn, priority, source)
    _rebuild()


def unregister_source(source: str) -> None:
    """Снять все фильтры мода source (при его выключении)."""
    for filter_id in [i for i, s in _FILTERS.items() if s.source == source]:
        del _FILTERS[filter_id]
    _rebuild()


def frame_filters() -> list[FrameFilterSpec]:
    return list(_ORDER)


def has_frame_filters() -> bool:
    """Есть ли вообще фильтры — чтобы горячий цикл не платил за пустую цепочку."""
    return bool(_ORDER)


def apply_frame_filters(colors: np.ndarray) -> np.ndarray:
    """Прогнать кадр через цепочку фильтров. Возвращает RGB-байты (N, 3).

    Фильтр, который упал или вернул None, считается пропущенным — кадр идёт
    дальше таким, каким пришёл к нему: подсветка не должна гаснуть из-за мода.
    """
    out = colors
    for spec in _ORDER:
        try:
            result = spec.fn(out)
        except Exception:  # noqa: BLE001 — битый фильтр не должен рвать вывод
            continue
        if result is not None:
            out = result
    if out is colors:
        return colors
    return np.clip(out, 0, 255).astype(np.uint8, copy=False)
