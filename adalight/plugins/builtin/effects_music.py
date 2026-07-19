"""Встроенный мод «Цветомузыка».

Эффекты режима «Цветомузыка» — это мод, идущий в комплекте. Он регистрирует
эффекты через тот же контракт, что доступен плагинам: register(api) →
api.register_music_effect(id, label, factory, wants_color). Фабрика создаёт
рендерер с состоянием (АРУ, история баса); цвет и чувствительность читаются
из cfg на лету, поэтому их смена не сбрасывает состояние.
"""

from __future__ import annotations

import numpy as np

from ...config import parse_hex_color
from ...effects import hsv_strip


class MusicRenderer:
    """Превращает аудиоблоки в цвета ленты. Держит АРУ (автоусиление),
    чтобы тихая и громкая музыка выглядели одинаково живо."""

    WAVE_HISTORY = 60  # кадров истории баса для бегущей волны

    def __init__(self, effect: str, n_leds: int):
        self.effect = effect
        self.n = n_leds
        self._peak = 1e-6
        self._smoothed = np.zeros(n_leds)
        self._wave_history = [0.0] * self.WAVE_HISTORY
        self._beat_avg = 1e-6
        self._beat_flash = 0.0

    def render(self, samples: np.ndarray, samplerate: int, cfg: dict) -> np.ndarray:
        gain = float(cfg["music_gain"])
        color = np.array(parse_hex_color(cfg["music_color"]), dtype=np.float64)
        if self.effect == "pulse":
            return self._pulse(samples, samplerate, color, gain)
        if self.effect == "wave":
            return self._wave(samples, samplerate, color, gain)
        if self.effect == "beat":
            return self._beat(samples, samplerate, color, gain)
        return self._spectrum(samples, samplerate, gain)

    def _agc(self, values: np.ndarray, gain: float) -> np.ndarray:
        """Нормировка на медленно затухающий пик; gain подкручивает чувствительность.

        Степень 0.45 — перцептивное сжатие: тихие полосы заметно подтягиваются
        (0.1 -> 0.35), иначе всё, что тише пика, выглядит почти чёрным.
        """
        self._peak = max(self._peak * 0.995, float(values.max()), 1e-6)
        norm = np.clip(values / self._peak, 0.0, 1.0)
        return np.clip(np.power(norm, 0.45) * gain, 0.0, 1.0)

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

    def _bass_level(self, samples: np.ndarray, samplerate: int, gain: float) -> float:
        """Энергия баса (40..150 Гц), нормированная АРУ в 0..1."""
        bass = self._bands(samples, samplerate, 12)[:3].mean()
        return float(self._agc(np.array([bass]), gain)[0])

    def _spectrum(self, samples: np.ndarray, samplerate: int, gain: float) -> np.ndarray:
        """Спектр по периметру: низкие частоты в начале ленты, высокие — в конце."""
        levels = self._agc(self._bands(samples, samplerate, self.n), gain)
        # инерция вниз, мгновенная атака вверх — так «бьётся» приятнее
        self._smoothed = np.maximum(levels, self._smoothed * 0.82)
        hues = 0.66 - 0.66 * np.arange(self.n) / max(self.n, 1)  # синий -> красный
        return hsv_strip(hues, self._smoothed)

    def _pulse(self, samples, samplerate, color, gain) -> np.ndarray:
        """Вся лента пульсирует одним цветом от энергии баса (40..150 Гц)."""
        level = self._bass_level(samples, samplerate, gain)
        self._smoothed = np.maximum(level, self._smoothed * 0.85)
        return np.tile(color * float(self._smoothed[0]), (self.n, 1))

    def _wave(self, samples, samplerate, color, gain) -> np.ndarray:
        """Волны от баса: рождаются в середине ленты и разбегаются к краям.

        История уровней баса — лента времени фиксированной длины: центр диода
        читает «сейчас», края — прошлое, поэтому всплеск баса виден как волна,
        уходящая от центра к краям.
        """
        self._wave_history.insert(0, self._bass_level(samples, samplerate, gain))
        del self._wave_history[self.WAVE_HISTORY :]
        history = np.array(self._wave_history)
        center = (self.n - 1) / 2.0
        dist = np.abs(np.arange(self.n) - center) / max(center, 1.0)  # 0..1
        idx = (dist * (self.WAVE_HISTORY - 1)).astype(int)
        return color * history[idx][:, None]

    def _beat(self, samples, samplerate, color, gain) -> np.ndarray:
        """Вспышки на битах: удар баса заметно выше среднего — вся лента вспыхивает."""
        bass = float(self._bands(samples, samplerate, 12)[:3].mean())
        self._beat_avg = self._beat_avg * 0.95 + bass * 0.05
        if bass > self._beat_avg * 1.6 and bass > 1e-6:
            self._beat_flash = 1.0
        else:
            self._beat_flash *= 0.82  # быстрое затухание между ударами
        level = min(self._beat_flash * gain, 1.0)
        return np.tile(color * level, (self.n, 1))


# (id, подпись, показывать ли контрол цвета) — источник правды для register() и тестов
MUSIC_EFFECTS = [
    ("spectrum", "Спектр по периметру", False),
    ("pulse", "Пульс от баса", True),
    ("wave", "Волны от баса", True),
    ("beat", "Вспышки на битах", True),
]


class EffectsMusicMod:
    name = "effects_music"
    title = "Цветомузыка"
    description = (
        "Эффекты режима «Цветомузыка»: спектр по периметру, пульс от баса, "
        "волны от баса, вспышки на битах. Встроенный мод — выключение уберёт "
        "эти эффекты."
    )
    base = True

    def register(self, api) -> None:
        for effect_id, label, wants_color in MUSIC_EFFECTS:
            api.register_music_effect(
                effect_id, label,
                lambda n, e=effect_id: MusicRenderer(e, n),
                wants_color=wants_color,
            )


def create_plugin() -> EffectsMusicMod:
    return EffectsMusicMod()
