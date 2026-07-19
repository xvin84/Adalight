"""Эффекты режимов «Лампа» и «Цветомузыка».

Каждый эффект отдаёт сырые RGB-цвета (N, 3) в диапазоне 0..255 — дальше они
проходят обычный конвейер устройства (насыщенность, температура, гамма,
яркость), поэтому расписание/ночной режим/адаптивность работают и здесь.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .config import parse_hex_color


def hsv_strip(hues: np.ndarray, value: np.ndarray | float = 1.0) -> np.ndarray:
    """Векторное HSV(S=1) -> RGB для массива оттенков 0..1; результат (N, 3) 0..255."""
    h = (np.asarray(hues, dtype=np.float64) % 1.0) * 6.0
    i = h.astype(int) % 6
    f = h - np.floor(h)
    v = np.broadcast_to(np.asarray(value, dtype=np.float64), h.shape)
    p = np.zeros_like(v)
    q = v * (1.0 - f)
    t = v * f
    lut = np.stack(
        [
            np.stack([v, t, p], axis=-1),
            np.stack([q, v, p], axis=-1),
            np.stack([p, v, t], axis=-1),
            np.stack([p, q, v], axis=-1),
            np.stack([t, p, v], axis=-1),
            np.stack([v, p, q], axis=-1),
        ],
        axis=0,
    )
    return lut[i, np.arange(len(h))] * 255.0


# ── лампа: реестр эффектов («всё есть мод») ────────────────────────────────
#
# Встроенные эффекты регистрируются тем же вызовом register_lamp_effect(), что
# доступен плагинам через PluginAPI.register_lamp_effect(). Функция эффекта —
# (cfg_like, n, t, points) -> RGB (n, 3) 0..255. Флаги wants_* говорят GUI,
# какие контролы показывать (цвет / градиент / скорость / настройки камина).

LampRender = Callable[[dict, int, float, "list | None"], np.ndarray]


@dataclass
class LampEffectSpec:
    id: str
    label: str
    render: LampRender
    wants_color: bool = False
    wants_gradient: bool = False
    wants_speed: bool = False
    wants_fire: bool = False
    source: str = ""  # имя мода, зарегистрировавшего эффект (для снятия)


_LAMP_EFFECTS: dict[str, LampEffectSpec] = {}


def register_lamp_effect(
    effect_id: str,
    label: str,
    render: LampRender,
    *,
    wants_color: bool = False,
    wants_gradient: bool = False,
    wants_speed: bool = False,
    wants_fire: bool = False,
    source: str = "",
) -> None:
    """Добавить эффект лампы в реестр (повторный id — перезапись)."""
    _LAMP_EFFECTS[effect_id] = LampEffectSpec(
        effect_id, label, render, wants_color, wants_gradient,
        wants_speed, wants_fire, source,
    )


def unregister_source(source: str) -> None:
    """Снять всё, что зарегистрировал мод source (эффекты лампы и цветомузыки)."""
    for effect_id in [i for i, s in _LAMP_EFFECTS.items() if s.source == source]:
        del _LAMP_EFFECTS[effect_id]
    for effect_id in [i for i, s in _MUSIC_EFFECTS.items() if s.source == source]:
        del _MUSIC_EFFECTS[effect_id]


def lamp_effects() -> list[LampEffectSpec]:
    return list(_LAMP_EFFECTS.values())


def lamp_effect(effect_id: str) -> LampEffectSpec | None:
    return _LAMP_EFFECTS.get(effect_id)


def render_lamp(
    cfg_like: dict, n: int, t: float, points: list | None = None
) -> np.ndarray:
    """Кадр лампы: диспатч по реестру. points — раскладка диодов (side, x, y)."""
    spec = _LAMP_EFFECTS.get(cfg_like["lamp_effect"]) or _LAMP_EFFECTS.get("solid")
    if spec is None:
        # ни выбранного эффекта, ни solid (мод «Эффекты лампы» выключен) —
        # безопасный запас: сплошной цвет лампы, чтобы движок не падал
        color = np.array(parse_hex_color(cfg_like["lamp_color"]), dtype=np.float64)
        return np.tile(color, (n, 1))
    return spec.render(cfg_like, n, t, points)


# ── цветомузыка: реестр эффектов ───────────────────────────────────────────
#
# Музыкальный эффект держит состояние (АРУ, история баса), поэтому регистрирует
# фабрику: factory(n_leds) -> объект с render(samples, samplerate, cfg) -> RGB.
# cfg — словарь настроек (music_color/music_gain), читается на лету.

MusicFactory = Callable[[int], object]


@dataclass
class MusicEffectSpec:
    id: str
    label: str
    factory: MusicFactory
    wants_color: bool = False
    source: str = ""


_MUSIC_EFFECTS: dict[str, MusicEffectSpec] = {}


def register_music_effect(
    effect_id: str,
    label: str,
    factory: MusicFactory,
    *,
    wants_color: bool = False,
    source: str = "",
) -> None:
    """Добавить эффект цветомузыки в реестр (повторный id — перезапись)."""
    _MUSIC_EFFECTS[effect_id] = MusicEffectSpec(
        effect_id, label, factory, wants_color, source
    )


def music_effects() -> list[MusicEffectSpec]:
    return list(_MUSIC_EFFECTS.values())


def music_effect(effect_id: str) -> MusicEffectSpec | None:
    return _MUSIC_EFFECTS.get(effect_id)


def make_music_renderer(effect_id: str, n_leds: int) -> object | None:
    """Свежий рендерер для эффекта из реестра (None — эффект не зарегистрирован)."""
    spec = _MUSIC_EFFECTS.get(effect_id)
    return spec.factory(n_leds) if spec is not None else None


# Реализации эффектов цветомузыки переехали в мод adalight.plugins.builtin.effects_music
