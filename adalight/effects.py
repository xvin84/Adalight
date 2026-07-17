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
        return render_fire(
            n,
            t,
            speed,
            points,
            height=float(cfg_like.get("fire_height", 1.0)),
            intensity=float(cfg_like.get("fire_intensity", 1.0)),
            sparks=int(cfg_like.get("fire_sparks", 2)),
        )

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

    if effect == "comet":
        # комета выбранного цвета бежит по периметру, за ней тает хвост
        head = (t * (0.05 + speed * 0.6)) % 1.0
        behind = (head - np.arange(n) / max(n, 1)) % 1.0  # доля круга позади головы
        tail = np.exp(-behind * 16.0)
        return color * tail[:, None]

    if effect == "aurora":
        # северное сияние: две медленные волны, оттенки зелёный <-> фиолетовый
        tt = t * (0.15 + speed * 0.85)
        pos = np.arange(n) / max(n, 1)
        w1 = np.sin(2.0 * np.pi * pos * 1.5 + tt * 0.9)
        w2 = np.sin(2.0 * np.pi * pos * 2.3 - tt * 0.6 + 1.7)
        hues = 0.55 + 0.23 * w1  # ~0.32 (зелёный) .. ~0.78 (фиолетовый)
        value = 0.35 + 0.55 * (0.5 + 0.5 * w2)
        return hsv_strip(hues, value)

    if effect == "starry":
        # звёздное небо: тёмная синева, звёзды мерцают каждая в своём ритме
        idx = np.arange(n)
        phases = (idx * 12.9898) % (2.0 * np.pi)
        freqs = 0.25 + (idx * 7.233) % 1.0  # 0.25..1.25 Гц у каждой звезды
        tw = np.sin(2.0 * np.pi * freqs * t * (0.25 + speed * 0.75) + phases)
        star = np.clip(tw, 0.0, 1.0) ** 6  # редкие острые вспышки
        sky = np.array([6.0, 10.0, 36.0])
        starlight = np.array([255.0, 240.0, 200.0])
        return sky + star[:, None] * (starlight - sky)

    raise ValueError(f"Неизвестный эффект лампы: {effect!r}")


def render_fire(
    n: int,
    t: float,
    speed: float,
    points: list | None,
    height: float = 1.0,
    intensity: float = 1.0,
    sparks: int = 2,
) -> np.ndarray:
    """Камин: очаг у нижней середины экрана, пламя затухает к верхним углам.

    Эффект детерминирован по t (без состояния): мерцание — смесь несоизмеримых
    синусов на диод, искры — псевдослучайные от номера «тика» времени.
    height — насколько высоко достаёт жар; intensity — общая яркость;
    sparks — сколько искр вспыхивает за раз.
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


# ── цветомузыка ──────────────────────────────────────────────────────────


class MusicRenderer:
    """Превращает аудиоблоки в цвета ленты. Держит АРУ (автоусиление),
    чтобы тихая и громкая музыка выглядели одинаково живо."""

    WAVE_HISTORY = 60  # кадров истории баса для бегущей волны

    def __init__(self, effect: str, color: str, gain: float, n_leds: int):
        self.effect = effect
        self.color = np.array(parse_hex_color(color), dtype=np.float64)
        self.gain = float(gain)
        self.n = n_leds
        self._peak = 1e-6
        self._smoothed = np.zeros(n_leds)
        self._wave_history = [0.0] * self.WAVE_HISTORY
        self._beat_avg = 1e-6
        self._beat_flash = 0.0

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
        if self.effect == "wave":
            return self._render_wave(samples, samplerate)
        if self.effect == "beat":
            return self._render_beat(samples, samplerate)
        return self._render_spectrum(samples, samplerate)

    def _bass_level(self, samples: np.ndarray, samplerate: int) -> float:
        """Энергия баса (40..150 Гц), нормированная АРУ в 0..1."""
        bass = self._bands(samples, samplerate, 12)[:3].mean()
        return float(self._agc(np.array([bass]))[0])

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
        level = self._bass_level(samples, samplerate)
        self._smoothed = np.maximum(level, self._smoothed * 0.85)
        return np.tile(self.color * float(self._smoothed[0]), (self.n, 1))

    def _render_wave(self, samples: np.ndarray, samplerate: int) -> np.ndarray:
        """Волны от баса: рождаются в середине ленты и разбегаются к краям.

        История уровней баса — лента времени фиксированной длины: центр диода
        читает «сейчас», края — прошлое, поэтому всплеск баса виден как волна,
        уходящая от центра к краям.
        """
        self._wave_history.insert(0, self._bass_level(samples, samplerate))
        del self._wave_history[self.WAVE_HISTORY :]
        history = np.array(self._wave_history)
        center = (self.n - 1) / 2.0
        dist = np.abs(np.arange(self.n) - center) / max(center, 1.0)  # 0..1
        idx = (dist * (self.WAVE_HISTORY - 1)).astype(int)
        return self.color * history[idx][:, None]

    def _render_beat(self, samples: np.ndarray, samplerate: int) -> np.ndarray:
        """Вспышки на битах: удар баса заметно выше среднего — вся лента вспыхивает."""
        bass = float(self._bands(samples, samplerate, 12)[:3].mean())
        self._beat_avg = self._beat_avg * 0.95 + bass * 0.05
        if bass > self._beat_avg * 1.6 and bass > 1e-6:
            self._beat_flash = 1.0
        else:
            self._beat_flash *= 0.82  # быстрое затухание между ударами
        level = min(self._beat_flash * self.gain, 1.0)
        return np.tile(self.color * level, (self.n, 1))
