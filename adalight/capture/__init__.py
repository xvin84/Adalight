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
            from .windows import BetterCamBackend, DxcamBackend

            reasons = []
            for cls in (BetterCamBackend, DxcamBackend):
                try:
                    return cls(cfg)
                except Exception as e:  # DXGI/ctypes могут падать чем угодно
                    reasons.append(f"{cls.__name__}: {e}")
            fallback_reason = "; ".join(reasons)
            name = "mss"
        elif _is_wayland():
            name = "wfrecorder"
        else:
            name = "mss"

    if name == "bettercam":
        from .windows import BetterCamBackend

        backend: BaseBackend = BetterCamBackend(cfg)
    elif name == "dxcam":
        from .windows import DxcamBackend

        backend = DxcamBackend(cfg)
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
