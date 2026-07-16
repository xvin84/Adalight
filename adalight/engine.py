"""Движок подсветки: цикл захват -> усреднение зон -> сглаживание -> отправка.

Не зависит от Qt: CLI использует его напрямую, GUI — в отдельном потоке через
колбэки. Параметры изображения (гамма/яркость/насыщенность/сглаживание),
расписание и адаптивная яркость меняются на лету через set_tuning() —
без перезапуска и без ресета платы.
"""

from __future__ import annotations

import datetime
import threading
import time
from collections.abc import Callable
from typing import Literal

import numpy as np

from .capture import create_backend
from .config import Config
from .device import AdalightDevice
from .geometry import LedGeometry, Slice
from .schedule import ScheduleRule, brightness_at, parse_rules

Mode = Literal["live", "chase", "sides", "off"]

SIDE_TEST_PALETTE = {
    "top": (255, 0, 0),      # красный
    "right": (0, 255, 0),    # зелёный
    "bottom": (0, 0, 255),   # синий
    "left": (255, 200, 0),   # жёлтый
}


def band_rects(
    width: int, height: int, band_size: float, sides: set[str]
) -> dict[str, tuple[int, int, int, int]]:
    """Прямоугольники краевых полос (left, top, width, height) для полосного захвата."""
    bw = max(1, int(width * band_size))
    bh = max(1, int(height * band_size))
    all_rects = {
        "top": (0, 0, width, bh),
        "bottom": (0, height - bh, width, bh),
        "left": (0, 0, bw, height),
        "right": (width - bw, 0, bw, height),
    }
    return {side: all_rects[side] for side in sides}


def localize_slice(side: str, slc: Slice, width: int, height: int, bw: int, bh: int) -> Slice:
    """Перевод зоны из координат полного кадра в координаты своей краевой полосы."""
    y1, y2, x1, x2 = slc
    if side == "bottom":
        return (y1 - (height - bh), y2 - (height - bh), x1, x2)
    if side == "right":
        return (y1, y2, x1 - (width - bw), x2 - (width - bw))
    return (y1, y2, x1, x2)  # top и left уже локальны


class Engine:
    def __init__(
        self,
        cfg: Config,
        on_colors: Callable[[np.ndarray], None] | None = None,
        on_fps: Callable[[float], None] | None = None,
        on_backend: Callable[[str], None] | None = None,
        backend_factory: Callable[[Config], object] = create_backend,
    ):
        cfg.validate()
        self.cfg = cfg
        self.geom = LedGeometry(cfg)
        self.device = AdalightDevice(cfg)
        self._on_colors = on_colors
        self._on_fps = on_fps
        self._on_backend = on_backend
        self._backend_factory = backend_factory
        self._stop = threading.Event()
        self._lock = threading.Lock()

        # живые параметры (могут меняться из GUI-потока)
        self._smooth = cfg.smooth
        self._default_brightness = cfg.brightness
        self._schedule_enabled = cfg.schedule_enabled
        self._rules: list[ScheduleRule] = (
            parse_rules(cfg.schedule) if cfg.schedule_enabled else []
        )
        self._adaptive_enabled = cfg.adaptive_enabled
        self._adaptive_min = cfg.adaptive_min
        self._adaptive_max = cfg.adaptive_max
        self._adaptive_speed = cfg.adaptive_speed

        self._lum_smoothed = 0.5  # сглаженная яркость сцены 0..1
        self._applied_brightness: float | None = None

    def stop(self) -> None:
        self._stop.set()

    def set_tuning(
        self,
        *,
        gamma: float | None = None,
        brightness: float | None = None,
        saturation: float | None = None,
        smooth: float | None = None,
        schedule_enabled: bool | None = None,
        schedule: list[dict] | None = None,
        adaptive_enabled: bool | None = None,
        adaptive_min: float | None = None,
        adaptive_max: float | None = None,
        adaptive_speed: float | None = None,
    ) -> None:
        """Применение «мягких» настроек на лету. schedule — сырой список из конфига."""
        with self._lock:
            if smooth is not None:
                self._smooth = smooth
            if brightness is not None:
                self._default_brightness = brightness
            if schedule_enabled is not None:
                self._schedule_enabled = schedule_enabled
            if schedule is not None:
                self._rules = parse_rules(schedule)
            if adaptive_enabled is not None:
                self._adaptive_enabled = adaptive_enabled
            if adaptive_min is not None:
                self._adaptive_min = adaptive_min
            if adaptive_max is not None:
                self._adaptive_max = adaptive_max
            if adaptive_speed is not None:
                self._adaptive_speed = adaptive_speed
            self.device.set_tuning(gamma=gamma, saturation=saturation)
            self._applied_brightness = None  # форсируем пересчёт итоговой яркости

    def run(self, mode: Mode = "live") -> None:
        if mode == "live":
            self._run_live()
        elif mode == "chase":
            self._run_chase()
        elif mode == "sides":
            self._run_sides()
        elif mode == "off":
            self._run_off()
        else:
            raise ValueError(f"Неизвестный режим: {mode!r}")

    # ── внутреннее ────────────────────────────────────────────────────────

    def _emit(self, colors: np.ndarray) -> None:
        if self._on_colors is not None:
            self._on_colors(np.asarray(colors, dtype=np.uint8).copy())

    def _effective_brightness(self, raw: np.ndarray | None) -> float:
        """Итоговая яркость: расписание (или дефолт) × адаптивный коэффициент."""
        with self._lock:
            base = self._default_brightness
            if self._schedule_enabled and self._rules:
                base = brightness_at(
                    datetime.datetime.now().time(), self._rules, self._default_brightness
                )
            if self._adaptive_enabled and raw is not None:
                lum = float(raw.mean()) / 255.0
                self._lum_smoothed += (lum - self._lum_smoothed) * self._adaptive_speed
                lo, hi = self._adaptive_min, self._adaptive_max
                base *= lo + (hi - lo) * self._lum_smoothed
        return round(base, 2)  # квантуем, чтобы не перестраивать LUT каждый кадр

    def _apply_brightness(self, raw: np.ndarray | None) -> None:
        eff = self._effective_brightness(raw)
        if eff != self._applied_brightness:
            self.device.set_tuning(brightness=eff)
            self._applied_brightness = eff

    def _run_live(self) -> None:
        backend = self._backend_factory(self.cfg)
        try:
            if self._on_backend is not None:
                note = f" ({backend.fallback_reason})" if backend.fallback_reason else ""
                self._on_backend(f"{type(backend).__name__}{note}")

            w, h = backend.width, backend.height
            slices = self.geom.calculate_slices(w, h)
            sides = [s for s, _, _ in self.geom.points]

            use_bands = backend.supports_bands
            if use_bands:
                bw = max(1, int(w * self.cfg.band_size))
                bh = max(1, int(h * self.cfg.band_size))
                rects = band_rects(w, h, self.cfg.band_size, set(sides))
                local = [
                    localize_slice(sides[i], slc, w, h, bw, bh)
                    for i, slc in enumerate(slices)
                ]

            self.device.connect()

            n = self.cfg.total_leds
            smoothed = np.zeros((n, 3))
            raw = np.empty((n, 3))
            frame_time = 1.0 / self.cfg.target_fps
            fps_t0, fps_n = time.monotonic(), 0

            while not self._stop.is_set():
                t0 = time.monotonic()

                got_frame = False
                if use_bands:
                    bands = backend.get_bands(rects)
                    for i, (y1, y2, x1, x2) in enumerate(local):
                        reg = bands[sides[i]][y1:y2, x1:x2]
                        raw[i] = reg.mean(axis=(0, 1)) if reg.size else 0.0
                    got_frame = True
                else:
                    img = backend.get_frame()
                    if img is not None:
                        for i, (y1, y2, x1, x2) in enumerate(slices):
                            reg = img[y1:y2, x1:x2]
                            raw[i] = reg.mean(axis=(0, 1)) if reg.size else 0.0
                        got_frame = True

                if got_frame:
                    self._apply_brightness(raw)
                    s = self._smooth
                    smoothed *= s
                    smoothed += raw * (1.0 - s)
                    final = self.device.send_processed(smoothed)
                    self._emit(final)

                fps_n += 1
                now = time.monotonic()
                if now - fps_t0 >= 1.0:
                    if self._on_fps is not None:
                        self._on_fps(fps_n / (now - fps_t0))
                    fps_t0, fps_n = now, 0

                dt = time.monotonic() - t0
                if dt < frame_time:
                    self._stop.wait(frame_time - dt)
        finally:
            self.device.close()
            backend.close()

    def _run_chase(self) -> None:
        self.device.connect()
        try:
            n = self.cfg.total_leds
            i = 0
            while not self._stop.is_set():
                colors = np.full((n, 3), 6, dtype=np.uint8)
                colors[i] = (255, 255, 255)
                self.device.send_raw(colors)
                self._emit(colors)
                i = (i + 1) % n
                self._stop.wait(0.12)
        finally:
            self.device.close()

    def _run_sides(self) -> None:
        colors = np.array(
            [SIDE_TEST_PALETTE[s] for s, _, _ in self.geom.points], dtype=np.uint8
        )
        self.device.connect()
        try:
            while not self._stop.is_set():
                self.device.send_raw(colors)
                self._emit(colors)
                self._stop.wait(0.5)
        finally:
            self.device.close()

    def _run_off(self) -> None:
        self.device.connect()
        self.device.close()  # close() гасит ленту перед закрытием порта
        self._emit(np.zeros((self.cfg.total_leds, 3), dtype=np.uint8))
