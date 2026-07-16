"""Графический интерфейс (PySide6)."""

from __future__ import annotations


def run() -> int:
    from .main_window import run as _run

    return _run()
