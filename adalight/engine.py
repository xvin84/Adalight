"""Движок подсветки: цикл захват -> усреднение зон -> сглаживание -> отправка.

Не зависит от Qt: CLI использует его напрямую, GUI — в отдельном потоке
через колбэки on_colors/on_fps.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Literal

import numpy as np

from .capture import create_backend
from .config import Config
from .device import AdalightDevice
from .geometry import LedGeometry

Mode = Literal["live", "chase", "sides", "off"]

SIDE_TEST_PALETTE = {
    "top": (255, 0, 0),      # красный
    "right": (0, 255, 0),    # зелёный
    "bottom": (0, 0, 255),   # синий
    "left": (255, 200, 0),   # жёлтый
}


class Engine:
    def __init__(
        self,
        cfg: Config,
        on_colors: Callable[[np.ndarray], None] | None = None,
        on_fps: Callable[[float], None] | None = None,
    ):
        cfg.validate()
        self.cfg = cfg
        self.geom = LedGeometry(cfg)
        self.device = AdalightDevice(cfg)
        self._on_colors = on_colors
        self._on_fps = on_fps
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

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

    def _run_live(self) -> None:
        backend = create_backend(self.cfg)
        try:
            slices = self.geom.calculate_slices(backend.width, backend.height)
            self.device.connect()

            n = self.cfg.total_leds
            smoothed = np.zeros((n, 3))
            raw = np.empty((n, 3))
            s = self.cfg.smooth
            frame_time = 1.0 / self.cfg.target_fps
            fps_t0, fps_n = time.monotonic(), 0

            while not self._stop.is_set():
                t0 = time.monotonic()
                img = backend.get_frame()

                if img is not None:
                    for i, (y1, y2, x1, x2) in enumerate(slices):
                        reg = img[y1:y2, x1:x2]
                        raw[i] = reg.mean(axis=(0, 1)) if reg.size else 0.0

                    # экспоненциальное сглаживание без лишних аллокаций
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
