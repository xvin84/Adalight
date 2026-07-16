"""Фабрика бэкендов захвата и перечисление мониторов."""

from __future__ import annotations

import os
import sys

from ..config import Config
from .base import BaseBackend, CaptureError

__all__ = ["BaseBackend", "CaptureError", "create_backend", "list_outputs"]


def _is_wayland() -> bool:
    return sys.platform.startswith("linux") and bool(os.environ.get("WAYLAND_DISPLAY"))


def create_backend(cfg: Config) -> BaseBackend:
    name = cfg.backend
    fallback_reason: str | None = None
    if name == "auto":
        if sys.platform == "win32":
            from .windows import DxcamBackend

            try:
                return DxcamBackend(cfg)
            except Exception as e:  # dxcam может упасть чем угодно (comtypes, DXGI)
                fallback_reason = f"dxcam недоступен: {e}"
                name = "mss"
        elif _is_wayland():
            name = "wfrecorder"
        else:
            name = "mss"

    if name == "dxcam":
        from .windows import DxcamBackend

        backend: BaseBackend = DxcamBackend(cfg)
    elif name == "mss":
        from .mss_backend import MssBackend

        backend = MssBackend(cfg)
    elif name == "wfrecorder":
        from .wayland import WfRecorderBackend

        backend = WfRecorderBackend(cfg)
    elif name == "grim":
        from .wayland import GrimBackend

        backend = GrimBackend(cfg)
    else:
        raise CaptureError(f"Неизвестный бэкенд захвата: {name!r}")

    backend.fallback_reason = fallback_reason
    return backend


def list_outputs() -> list[tuple[str, str]]:
    """Доступные мониторы: (значение для cfg.output, человекочитаемое описание)."""
    if _is_wayland():
        try:
            from .wayland import hyprland_monitors

            return [
                (m["name"], f"{m['name']} ({m['width']}x{m['height']})")
                for m in hyprland_monitors()
            ]
        except CaptureError:
            return []
    try:
        import mss

        with mss.mss() as sct:
            return [
                (str(i), f"Экран {i} ({m['width']}x{m['height']})")
                for i, m in enumerate(sct.monitors[1:])
            ]
    except Exception:
        return []
