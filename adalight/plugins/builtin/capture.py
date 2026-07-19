"""Встроенный мод «Захват экрана».

Штатные источники захвата (bettercam/dxcam/mss на Windows, wf-recorder/grim на
Wayland) — это мод, идущий в комплекте. Выключишь — режим «Захват экрана»
останется без источников (с предупреждением в менеджере).
"""

from __future__ import annotations

from ...capture import register_builtin_capture_sources


class CaptureMod:
    name = "capture"
    title = "Захват экрана"
    description = (
        "Источники захвата экрана: bettercam / dxcam / mss (Windows), "
        "wf-recorder / grim (Wayland). Встроенный мод — выключение оставит "
        "режим «Захват экрана» без источников."
    )
    base = True

    def register(self, api) -> None:
        register_builtin_capture_sources(source="capture")


def create_plugin() -> CaptureMod:
    return CaptureMod()
