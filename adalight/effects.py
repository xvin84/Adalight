"""Эффекты режимов «Лампа» и «Цветомузыка».

Каждый эффект отдаёт сырые RGB-цвета (N, 3) в диапазоне 0..255 — дальше они
проходят обычный конвейер устройства (насыщенность, температура, гамма,
яркость), поэтому расписание/ночной режим/адаптивность работают и здесь.
"""

from __future__ import annotations

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


# ── лампа ────────────────────────────────────────────────────────────────


def render_lamp(
    cfg_like: dict, n: int, t: float, points: list | None = None
) -> np.ndarray:
    """Кадр лампы: effect/color/gradient/speed из dict'а (см. Engine), t — секунды.

    points — раскладка диодов (side, x, y) для эффектов, зависящих от геометрии.
    """
    effect = cfg_like["lamp_effect"]
    color = np.array(parse_hex_color(cfg_like["lamp_color"]), dtype=np.float64)
    speed = float(cfg_like["lamp_speed"])

    if effect == "fire":
        return render_fire(n, t, speed, points)

    if effect == "solid":
        return np.tile(color, (n, 1))

    if effect == "gradient":
        stops = sorted(cfg_like["lamp_gradient"], key=lambda s: float(s["pos"]))
        pos = np.array([float(s["pos"]) for s in stops])
        cols = np.array([parse_hex_color(s["color"]) for s in stops], dtype=np.float64)
        x = np.linspace(0.0, 1.0, max(n, 2))
        return np.stack([np.interp(x, pos, cols[:, c]) for c in range(3)], axis=1)

    if effect == "rainbow":
        # бегущая радуга: оттенки вдоль ленты вращаются по периметру
        hues = np.arange(n) / max(n, 1) + t * speed * 0.2
        return hsv_strip(hues)

    if effect == "rainbow_static":
        # статичная радуга: неподвижное распределение оттенков вдоль ленты
        return hsv_strip(np.arange(n) / max(n, 1))

    if effect == "breathing":
        # плавное «дыхание» 0.12..1.0; speed=1 -> цикл ~2 с, speed→0 -> очень медленно
        phase = np.sin(2.0 * np.pi * t * (0.05 + speed * 0.45))
        factor = 0.12 + 0.88 * (0.5 + 0.5 * phase)
        return np.tile(color * factor, (n, 1))

    raise ValueError(f"Неизвестный эффект лампы: {effect!r}")


def render_fire(n: int, t: float, speed: float, points: list | None) -> np.ndarray:
    """Камин: очаг у нижней середины экрана, пламя затухает к верхним углам.

    Эффект детерминирован по t (без состояния): мерцание — смесь несоизмеримых
    синусов на диод, искры — псевдослучайные от номера «тика» времени.
    """
    tt = t * (0.5 + 1.7 * speed)
    idx = np.arange(n)

    # базовый «жар»: расстояние от очага (0.5, 1.0) в нормированных координатах
    if points and len(points) == n:
        xs = np.array([x for _, x, _ in points])
        ys = np.array([y for _, _, y in points])
        dist = np.sqrt((xs - 0.5) ** 2 + (ys - 1.0) ** 2)
        heat = np.clip(1.0 - dist / 1.15, 0.06, 1.0)
    else:  # без геометрии — равномерный костёр
        heat = np.full(n, 0.6)

    # мерцание: два синуса с несоизмеримыми частотами и фазами на диод
    flicker = (
        0.5
        + 0.28 * np.sin(6.3 * tt + idx * 2.39996)
        + 0.22 * np.sin(11.7 * tt + idx * 1.7 + 3.0)
    )
    v = np.clip(heat * (0.45 + 0.65 * flicker), 0.0, 1.0)

    # огненная палитра: тлеющий красный -> оранжевый -> жёлтый
    out = np.zeros((n, 3))
    out[:, 0] = np.clip(v * 2.2, 0.0, 1.0) * 255.0
    out[:, 1] = np.clip(v * 1.6 - 0.35, 0.0, 1.0) * 200.0
    out[:, 2] = np.clip(v * 2.6 - 2.0, 0.0, 1.0) * 90.0

    # искорки: раз в ~0.35 с вспыхивают 1-2 диода в тёплой зоне
    tick = int(tt / 0.35)
    rng = np.random.default_rng(tick)
    fade = 1.0 - (tt / 0.35 - tick)  # искра гаснет в течение тика
    weights = heat / heat.sum()
    for spark in rng.choice(n, size=min(2, n), p=weights, replace=False):
        if rng.random() < 0.7:
            out[spark] = np.minimum(
                out[spark] + np.array([255, 220, 130]) * fade, 255.0
            )
    return out


# ── цветомузыка ──────────────────────────────────────────────────────────


class MusicRenderer:
    """Превращает аудиоблоки в цвета ленты. Держит АРУ (автоусиление),
    чтобы тихая и громкая музыка выглядели одинаково живо."""

    def __init__(self, effect: str, color: str, gain: float, n_leds: int):
        self.effect = effect
        self.color = np.array(parse_hex_color(color), dtype=np.float64)
        self.gain = float(gain)
        self.n = n_leds
        self._peak = 1e-6
        self._smoothed = np.zeros(n_leds)

    def _agc(self, values: np.ndarray) -> np.ndarray:
        """Нормировка на медленно затухающий пик; gain подкручивает чувствительность.

        Степень 0.45 — перцептивное сжатие: тихие полосы заметно подтягиваются
        (0.1 -> 0.35), иначе всё, что тише пика, выглядит почти чёрным.
        """
        self._peak = max(self._peak * 0.995, float(values.max()), 1e-6)
        norm = np.clip(values / self._peak, 0.0, 1.0)
        return np.clip(np.power(norm, 0.45) * self.gain, 0.0, 1.0)

    def render(self, samples: np.ndarray, samplerate: int) -> np.ndarray:
        if self.effect == "pulse":
            return self._render_pulse(samples, samplerate)
        return self._render_spectrum(samples, samplerate)

    def _bands(self, samples: np.ndarray, samplerate: int, count: int) -> np.ndarray:
        """Логарифмические частотные полосы 40 Гц..8 кГц."""
        spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
        freqs = np.fft.rfftfreq(len(samples), 1.0 / samplerate)
        edges = np.geomspace(40.0, 8000.0, count + 1)
        bands = np.zeros(count)
        for i in range(count):
            mask = (freqs >= edges[i]) & (freqs < edges[i + 1])
            if mask.any():
                bands[i] = spectrum[mask].mean()
        return bands

    def _render_spectrum(self, samples: np.ndarray, samplerate: int) -> np.ndarray:
        """Спектр по периметру: низкие частоты в начале ленты, высокие — в конце."""
        levels = self._agc(self._bands(samples, samplerate, self.n))
        # инерция вниз, мгновенная атака вверх — так «бьётся» приятнее
        self._smoothed = np.maximum(levels, self._smoothed * 0.82)
        hues = 0.66 - 0.66 * np.arange(self.n) / max(self.n, 1)  # синий -> красный
        return hsv_strip(hues, self._smoothed)

    def _render_pulse(self, samples: np.ndarray, samplerate: int) -> np.ndarray:
        """Вся лента пульсирует одним цветом от энергии баса (40..150 Гц)."""
        bass = self._bands(samples, samplerate, 12)[:3].mean()
        level = float(self._agc(np.array([bass]))[0])
        self._smoothed = np.maximum(level, self._smoothed * 0.85)
        return np.tile(self.color * float(self._smoothed[0]), (self.n, 1))
