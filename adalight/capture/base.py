"""Базовый интерфейс бэкенда захвата экрана."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class CaptureError(RuntimeError):
    pass


class BaseBackend(ABC):
    """Отдаёт кадры RGB (H, W, 3) uint8. width/height известны после конструктора.

    Если supports_bands=True, бэкенд умеет захватывать только краевые полосы
    через get_bands() — это сильно дешевле полного кадра.
    """

    width: int
    height: int
    supports_bands: bool = False
    fallback_reason: str | None = None  # чем не устроил основной бэкенд (режим auto)

    def get_bands(self, rects: dict[str, tuple[int, int, int, int]]) -> dict[str, np.ndarray]:
        """Захват полос {side: (left, top, width, height)} -> {side: RGB-массив}."""
        raise NotImplementedError

    @abstractmethod
    def get_frame(self) -> np.ndarray | None:
        """Следующий кадр или None, если нового кадра пока нет."""

    def close(self) -> None:  # noqa: B027 — освобождение ресурсов опционально
        pass
