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
    """Снять все эффекты, зарегистрированные модом source (при его выключении)."""
    for effect_id in [i for i, s in _LAMP_EFFECTS.items() if s.source == source]:
        del _LAMP_EFFECTS[effect_id]


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
