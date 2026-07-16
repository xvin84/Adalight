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
    if name == "auto":
        if sys.platform == "win32":
            from .windows import DxcamBackend

            try:
                return DxcamBackend(cfg)
            except CaptureError:
                name = "mss"
        elif _is_wayland():
            name = "wfrecorder"
        else:
            name = "mss"

    if name == "dxcam":
        from .windows import DxcamBackend

        return DxcamBackend(cfg)
    if name == "mss":
        from .mss_backend import MssBackend

        return MssBackend(cfg)
    if name == "wfrecorder":
        from .wayland import WfRecorderBackend

        return WfRecorderBackend(cfg)
    if name == "grim":
        from .wayland import GrimBackend

        return GrimBackend(cfg)
    raise CaptureError(f"Неизвестный бэкенд захвата: {name!r}")


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
