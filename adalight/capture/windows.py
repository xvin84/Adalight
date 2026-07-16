"""Бэкенды захвата для Windows: bettercam и dxcam (DXGI Desktop Duplication).

bettercam — поддерживаемый форк dxcam с тем же API и исправленными багами,
поэтому в режиме auto пробуется первым. Обе библиотеки используются в режиме
прямого опроса grab(): без фонового потока захвата, который в dxcam молча
умирает («не отдал ни одного кадра»). grab() возвращает None, пока картинка
не меняется, — это нормально, движок просто держит прежние цвета.
"""

from __future__ import annotations

import time

import numpy as np

from ..config import Config
from .base import BaseBackend, CaptureError


def parse_output_index(output: str) -> int:
    """cfg.output на Windows — номер экрана ('' = 0)."""
    if not output:
        return 0
    try:
        return int(output.split(":", 1)[0])
    except ValueError as e:
        raise CaptureError(
            f"На Windows поле 'монитор' должно быть номером экрана, получено {output!r}"
        ) from e


class _DuplicationBackend(BaseBackend):
    """Общая обвязка: у bettercam и dxcam одинаковый интерфейс камеры."""

    WARMUP_S = 2.0

    def __init__(self, cfg: Config, module) -> None:
        self._cam = module.create(
            output_idx=parse_output_index(cfg.output), output_color="RGB"
        )
        if self._cam is None:
            raise CaptureError(f"{module.__name__} не смог инициализировать захват экрана")
        self.width = int(self._cam.width)
        self.height = int(self._cam.height)

        # прогрев: DXGI отдаёт первый кадр только после изменения картинки,
        # поэтому отсутствие кадра за время прогрева — не ошибка
        t0 = time.monotonic()
        while self._cam.grab() is None and time.monotonic() - t0 < self.WARMUP_S:
            time.sleep(0.05)

    def get_frame(self) -> np.ndarray | None:
        return self._cam.grab()  # None, если кадр не обновился

    def close(self) -> None:
        try:
            self._cam.release()
        except Exception:
            pass


class BetterCamBackend(_DuplicationBackend):
    def __init__(self, cfg: Config):
        try:
            import bettercam
        except ImportError as e:
            raise CaptureError("Библиотека bettercam не установлена") from e
        super().__init__(cfg, bettercam)


class DxcamBackend(_DuplicationBackend):
    def __init__(self, cfg: Config):
        try:
            import dxcam
        except ImportError as e:
            raise CaptureError("Библиотека dxcam не установлена") from e
        super().__init__(cfg, dxcam)
