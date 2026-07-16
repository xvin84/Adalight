"""Кроссплатформенный запасной бэкенд захвата через mss (Windows, X11, macOS)."""

from __future__ import annotations

import numpy as np

from ..config import Config
from .base import BaseBackend, CaptureError


class MssBackend(BaseBackend):
    def __init__(self, cfg: Config):
        try:
            import mss
        except ImportError as e:
            raise CaptureError("Библиотека mss не установлена") from e

        self._sct = mss.mss()
        # monitors[0] — объединение всех экранов, реальные начинаются с 1
        real = self._sct.monitors[1:]
        if not real:
            raise CaptureError("mss не нашёл ни одного монитора")

        idx = 0
        if cfg.output:
            try:
                idx = int(cfg.output.split(":", 1)[0])
            except ValueError as e:
                raise CaptureError(
                    f"Для mss поле 'монитор' должно быть номером экрана, получено {cfg.output!r}"
                ) from e
        if not 0 <= idx < len(real):
            raise CaptureError(f"Экран {idx} не найден (доступно: 0..{len(real) - 1})")

        self._mon = real[idx]
        first = self.get_frame()
        self.height, self.width = first.shape[:2]

    def get_frame(self) -> np.ndarray | None:
        img = self._sct.grab(self._mon)
        # BGRA -> RGB
        return np.frombuffer(img.bgra, np.uint8).reshape((img.height, img.width, 4))[..., 2::-1]

    def close(self) -> None:
        self._sct.close()
