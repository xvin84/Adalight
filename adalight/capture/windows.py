"""Бэкенд захвата для Windows: DXGI Desktop Duplication через dxcam."""

from __future__ import annotations

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


class DxcamBackend(BaseBackend):
    """Высокопроизводительный захват (60+ FPS) без копий через GPU."""

    def __init__(self, cfg: Config):
        try:
            import dxcam
        except ImportError as e:
            raise CaptureError("Библиотека dxcam не установлена") from e

        self._cam = dxcam.create(output_idx=parse_output_index(cfg.output), output_color="RGB")
        if self._cam is None:
            raise CaptureError("dxcam не смог инициализировать захват экрана")

        self._cam.start(target_fps=cfg.target_fps, video_mode=True)
        first = self._cam.get_latest_frame()
        if first is None:
            self.close()
            raise CaptureError("dxcam не отдал ни одного кадра")
        self.height, self.width = first.shape[:2]

    def get_frame(self) -> np.ndarray | None:
        return self._cam.get_latest_frame()

    def close(self) -> None:
        try:
            self._cam.stop()
        except Exception:
            pass
