"""Встроенный мод «Эффекты лампы».

Все эффекты режима «Лампа» — это мод, идущий в комплекте (как базовый мод в
Factorio). Он регистрирует эффекты через тот же контракт, что доступен любому
плагину: `register(api)` → `api.register_lamp_effect(...)`. Пока мод включён,
эффекты есть в списке; выключишь — исчезнут (с предупреждением в менеджере).
"""

from __future__ import annotations

import numpy as np

from ...config import parse_hex_color
from ...effects import hsv_strip


def _lamp_color(cfg: dict) -> np.ndarray:
    return np.array(parse_hex_color(cfg["lamp_color"]), dtype=np.float64)


def _solid(cfg, n, t, points):
    return np.tile(_lamp_color(cfg), (n, 1))


def _gradient(cfg, n, t, points):
    stops = sorted(cfg["lamp_gradient"], key=lambda s: float(s["pos"]))
    pos = np.array([float(s["pos"]) for s in stops])
    cols = np.array([parse_hex_color(s["color"]) for s in stops], dtype=np.float64)
    x = np.linspace(0.0, 1.0, max(n, 2))
    return np.stack([np.interp(x, pos, cols[:, c]) for c in range(3)], axis=1)


def _rainbow(cfg, n, t, points):
    # бегущая радуга: оттенки вдоль ленты вращаются по периметру
    hues = np.arange(n) / max(n, 1) + t * float(cfg["lamp_speed"]) * 0.2
    return hsv_strip(hues)


def _rainbow_static(cfg, n, t, points):
    # статичная радуга: неподвижное распределение оттенков вдоль ленты
    return hsv_strip(np.arange(n) / max(n, 1))


def _breathing(cfg, n, t, points):
    # плавное «дыхание» 0.12..1.0; speed=1 -> цикл ~2 с, speed→0 -> очень медленно
    phase = np.sin(2.0 * np.pi * t * (0.05 + float(cfg["lamp_speed"]) * 0.45))
    factor = 0.12 + 0.88 * (0.5 + 0.5 * phase)
    return np.tile(_lamp_color(cfg) * factor, (n, 1))


def _comet(cfg, n, t, points):
    # комета выбранного цвета бежит по периметру, за ней тает хвост
    head = (t * (0.05 + float(cfg["lamp_speed"]) * 0.6)) % 1.0
    behind = (head - np.arange(n) / max(n, 1)) % 1.0  # доля круга позади головы
    tail = np.exp(-behind * 16.0)
    return _lamp_color(cfg) * tail[:, None]


def _aurora(cfg, n, t, points):
    # северное сияние: две медленные волны, оттенки зелёный <-> фиолетовый
    tt = t * (0.15 + float(cfg["lamp_speed"]) * 0.85)
    pos = np.arange(n) / max(n, 1)
    w1 = np.sin(2.0 * np.pi * pos * 1.5 + tt * 0.9)
    w2 = np.sin(2.0 * np.pi * pos * 2.3 - tt * 0.6 + 1.7)
    hues = 0.55 + 0.23 * w1  # ~0.32 (зелёный) .. ~0.78 (фиолетовый)
    value = 0.35 + 0.55 * (0.5 + 0.5 * w2)
    return hsv_strip(hues, value)


def _starry(cfg, n, t, points):
    # звёздное небо: тёмная синева, звёзды мерцают каждая в своём ритме
    idx = np.arange(n)
    phases = (idx * 12.9898) % (2.0 * np.pi)
    freqs = 0.25 + (idx * 7.233) % 1.0  # 0.25..1.25 Гц у каждой звезды
    tw = np.sin(2.0 * np.pi * freqs * t * (0.25 + float(cfg["lamp_speed"]) * 0.75) + phases)
    star = np.clip(tw, 0.0, 1.0) ** 6  # редкие острые вспышки
    sky = np.array([6.0, 10.0, 36.0])
    starlight = np.array([255.0, 240.0, 200.0])
    return sky + star[:, None] * (starlight - sky)


def _render_fire(n, t, speed, points, height=1.0, intensity=1.0, sparks=2):
    """Камин: очаг у нижней середины экрана, пламя затухает к верхним углам.

    Детерминирован по t (без состояния): мерцание — смесь несоизмеримых синусов
    на диод, искры — псевдослучайные от номера «тика» времени.
    """
    tt = t * (0.5 + 1.7 * speed)
    idx = np.arange(n)

    # базовый «жар»: расстояние от очага (0.5, 1.0) в нормированных координатах
    if points and len(points) == n:
        xs = np.array([x for _, x, _ in points])
        ys = np.array([y for _, _, y in points])
        dist = np.sqrt((xs - 0.5) ** 2 + (ys - 1.0) ** 2)
        heat = np.clip(1.0 - dist / (1.15 * height), 0.04, 1.0)
    else:  # без геометрии — равномерный костёр
        heat = np.full(n, 0.6)

    # мерцание: два синуса с несоизмеримыми частотами и фазами на диод
    flicker = (
        0.5
        + 0.28 * np.sin(6.3 * tt + idx * 2.39996)
        + 0.22 * np.sin(11.7 * tt + idx * 1.7 + 3.0)
    )
    v = np.clip(heat * (0.45 + 0.65 * flicker) * intensity, 0.0, 1.0)

    # огненная палитра: тлеющий красный -> оранжевый -> жёлтый
    out = np.zeros((n, 3))
    out[:, 0] = np.clip(v * 2.2, 0.0, 1.0) * 255.0
    out[:, 1] = np.clip(v * 1.6 - 0.35, 0.0, 1.0) * 200.0
    out[:, 2] = np.clip(v * 2.6 - 2.0, 0.0, 1.0) * 90.0

    # искорки: раз в ~0.35 с вспыхивает несколько диодов в тёплой зоне
    if sparks > 0:
        tick = int(tt / 0.35)
        rng = np.random.default_rng(tick)
        fade = 1.0 - (tt / 0.35 - tick)  # искра гаснет в течение тика
        weights = heat / heat.sum()
        for spark in rng.choice(n, size=min(sparks, n), p=weights, replace=False):
            if rng.random() < 0.75:
                out[spark] = np.minimum(
                    out[spark] + np.array([255, 220, 130]) * fade, 255.0
                )
    return out


def _fire(cfg, n, t, points):
    return _render_fire(
        n, t, float(cfg["lamp_speed"]), points,
        height=float(cfg.get("fire_height", 1.0)),
        intensity=float(cfg.get("fire_intensity", 1.0)),
        sparks=int(cfg.get("fire_sparks", 2)),
    )


# (id, подпись, render, флаги контролов) — источник правды для register() и тестов
LAMP_EFFECTS = [
    ("solid", "Сплошной цвет", _solid, {"wants_color": True}),
    ("gradient", "Градиент", _gradient, {"wants_gradient": True}),
    ("rainbow", "Радуга (бегущая)", _rainbow, {"wants_speed": True}),
    ("rainbow_static", "Радуга (статичная)", _rainbow_static, {}),
    ("breathing", "Дыхание", _breathing, {"wants_color": True, "wants_speed": True}),
    ("fire", "Камин", _fire, {"wants_speed": True, "wants_fire": True}),
    ("comet", "Комета", _comet, {"wants_color": True, "wants_speed": True}),
    ("aurora", "Северное сияние", _aurora, {"wants_speed": True}),
    ("starry", "Звёздное небо", _starry, {"wants_speed": True}),
]


class EffectsLampMod:
    name = "effects_lamp"
    title = "Эффекты лампы"
    description = (
        "Эффекты режима «Лампа»: цвет, градиент, радуги, дыхание, камин, комета, "
        "северное сияние, звёздное небо. Встроенный мод — выключение уберёт эффекты."
    )
    base = True  # базовый мод: предупреждать при выключении

    def register(self, api) -> None:
        for effect_id, label, render, flags in LAMP_EFFECTS:
            api.register_lamp_effect(effect_id, label, render, **flags)


def create_plugin() -> EffectsLampMod:
    return EffectsLampMod()
