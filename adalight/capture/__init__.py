"""Реестр источников захвата экрана и перечисление мониторов.

Источники захвата регистрируются как провайдеры (мод «Захват экрана» или
плагин) через register_capture_source(). create_backend() выбирает источник по
cfg.backend, а в режиме "auto" — лучший доступный для платформы по приоритету.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

from ..config import Config
from .base import BaseBackend, CaptureError

__all__ = [
    "BaseBackend",
    "CaptureError",
    "CaptureSourceSpec",
    "create_backend",
    "list_outputs",
    "register_capture_source",
    "capture_sources",
    "capture_source",
    "register_builtin_capture_sources",
]


def _is_wayland() -> bool:
    return sys.platform.startswith("linux") and bool(os.environ.get("WAYLAND_DISPLAY"))


def _current_platform() -> str:
    if sys.platform == "win32":
        return "win"
    if _is_wayland():
        return "wayland"
    return "linux"


# ── реестр источников захвата ──────────────────────────────────────────────

CaptureFactory = Callable[[Config], BaseBackend]


@dataclass
class CaptureSourceSpec:
    id: str
    label: str
    factory: CaptureFactory
    platforms: tuple[str, ...]  # win | wayland | linux | any
    priority: int = 50          # для "auto": меньше — пробуется раньше
    source: str = ""            # имя мода (для снятия при выключении)


_CAPTURE_SOURCES: dict[str, CaptureSourceSpec] = {}


def register_capture_source(
    source_id: str,
    label: str,
    factory: CaptureFactory,
    *,
    platforms: tuple[str, ...] = ("any",),
    priority: int = 50,
    source: str = "",
) -> None:
    """Добавить источник захвата в реестр (повторный id — перезапись)."""
    _CAPTURE_SOURCES[source_id] = CaptureSourceSpec(
        source_id, label, factory, platforms, priority, source
    )


def unregister_source(source: str) -> None:
    """Снять источники, зарегистрированные модом source (при его выключении)."""
    for source_id in [i for i, s in _CAPTURE_SOURCES.items() if s.source == source]:
        del _CAPTURE_SOURCES[source_id]


def capture_sources() -> list[CaptureSourceSpec]:
    return list(_CAPTURE_SOURCES.values())


def capture_source(source_id: str) -> CaptureSourceSpec | None:
    return _CAPTURE_SOURCES.get(source_id)


def create_backend(cfg: Config) -> BaseBackend:
    """Создать бэкенд захвата по cfg.backend ("auto" — лучший для платформы)."""
    if cfg.backend == "auto":
        plat = _current_platform()
        candidates = sorted(
            (s for s in _CAPTURE_SOURCES.values()
             if plat in s.platforms or "any" in s.platforms),
            key=lambda s: s.priority,
        )
        if not candidates:
            raise CaptureError("Нет источников захвата — включите мод «Захват экрана»")
        reasons: list[str] = []
        for spec in candidates:
            try:
                backend = spec.factory(cfg)
            except Exception as e:  # noqa: BLE001 — DXGI/ctypes падают чем угодно
                reasons.append(f"{spec.id}: {e}")
                continue
            backend.fallback_reason = "; ".join(reasons) or None
            return backend
        raise CaptureError("Захват не удался: " + "; ".join(reasons))

    spec = _CAPTURE_SOURCES.get(cfg.backend)
    if spec is None:
        raise CaptureError(f"Неизвестный источник захвата: {cfg.backend!r}")
    return spec.factory(cfg)


# ── встроенные источники ───────────────────────────────────────────────────


def register_builtin_capture_sources(source: str = "capture") -> None:
    """Зарегистрировать штатные источники (зовёт мод «Захват экрана» и CLI)."""

    def bettercam(cfg: Config) -> BaseBackend:
        from .windows import BetterCamBackend

        return BetterCamBackend(cfg)

    def dxcam(cfg: Config) -> BaseBackend:
        from .windows import DxcamBackend

        return DxcamBackend(cfg)

    def mss_backend(cfg: Config) -> BaseBackend:
        from .mss_backend import MssBackend

        return MssBackend(cfg)

    def wfrecorder(cfg: Config) -> BaseBackend:
        from .wayland import WfRecorderBackend

        return WfRecorderBackend(cfg)

    def grim(cfg: Config) -> BaseBackend:
        from .wayland import GrimBackend

        return GrimBackend(cfg)

    reg = lambda *a, **k: register_capture_source(*a, source=source, **k)  # noqa: E731
    reg("bettercam", "bettercam (DXGI)", bettercam, platforms=("win",), priority=10)
    reg("dxcam", "dxcam (DXGI)", dxcam, platforms=("win",), priority=20)
    reg("mss", "mss", mss_backend, platforms=("win", "linux"), priority=90)
    reg("wfrecorder", "wf-recorder (Wayland)", wfrecorder, platforms=("wayland",), priority=10)
    reg("grim", "grim (Wayland)", grim, platforms=("wayland",), priority=30)


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
    except Exception:  # noqa: BLE001
        return []
