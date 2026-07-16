"""Базовый интерфейс бэкенда захвата экрана."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class CaptureError(RuntimeError):
    pass


class BaseBackend(ABC):
    """Отдаёт кадры RGB (H, W, 3) uint8. width/height известны после конструктора."""

    width: int
    height: int

    @abstractmethod
    def get_frame(self) -> np.ndarray | None:
        """Следующий кадр или None, если нового кадра пока нет."""

    def close(self) -> None:  # noqa: B027 — освобождение ресурсов опционально
        pass
