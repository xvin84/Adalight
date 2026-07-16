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


def render_lamp(cfg_like: dict, n: int, t: float) -> np.ndarray:
    """Кадр лампы: effect/color/color2/speed из dict'а (см. Engine), t — секунды."""
    effect = cfg_like["lamp_effect"]
    color = np.array(parse_hex_color(cfg_like["lamp_color"]), dtype=np.float64)
    speed = float(cfg_like["lamp_speed"])

    if effect == "solid":
        return np.tile(color, (n, 1))

    if effect == "gradient":
        color2 = np.array(parse_hex_color(cfg_like["lamp_color2"]), dtype=np.float64)
        k = np.linspace(0.0, 1.0, max(n, 2))[:, None]
        return color * (1.0 - k) + color2 * k

    if effect == "rainbow":
        # оттенок вдоль ленты, медленно вращается со скоростью speed
        hues = np.arange(n) / max(n, 1) + t * speed * 0.2
        return hsv_strip(hues)

    if effect == "breathing":
        # плавное «дыхание» 0.12..1.0; speed=1 -> цикл ~2 с, speed→0 -> очень медленно
        phase = np.sin(2.0 * np.pi * t * (0.05 + speed * 0.45))
        factor = 0.12 + 0.88 * (0.5 + 0.5 * phase)
        return np.tile(color * factor, (n, 1))

    raise ValueError(f"Неизвестный эффект лампы: {effect!r}")


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
        """Нормировка на медленно затухающий пик; gain подкручивает чувствительность."""
        self._peak = max(self._peak * 0.995, float(values.max()), 1e-6)
        return np.clip(values / self._peak * self.gain, 0.0, 1.0)

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
