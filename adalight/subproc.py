"""Запуск сторонних программ из собранного бинарника.

PyInstaller в режиме onefile подставляет в LD_LIBRARY_PATH свою временную папку
(_MEIxxxx) с библиотеками, собранными на Ubuntu, и дочерние процессы наследуют
её. Системная утилита (hyprctl, grim, wf-recorder, pkexec) грузит оттуда чужой
libstdc++ и падает ещё до работы: «version GLIBCXX_3.4.35 not found» — на Arch
и других дистрибутивах со свежим toolchain это ломало весь захват на Wayland.

Поэтому внешние программы запускаем только через run()/popen() отсюда: они
возвращают окружение к тому, каким оно было до старта бандла.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from typing import Any

# Пути к библиотекам, которые подменяет бутлоадер PyInstaller. Исходное значение
# он кладёт в <VAR>_ORIG — и только если переменная вообще была задана, поэтому
# отсутствие _ORIG в собранном приложении означает «до запуска её не было».
_LIB_PATH_VARS = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "LIBPATH")


def system_env() -> dict[str, str]:
    """Окружение без следов PyInstaller — для сторонних программ и перезапуска."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("_PYI_") and k != "_MEIPASS2"
    }
    frozen = bool(getattr(sys, "frozen", False))
    for var in _LIB_PATH_VARS:
        original = env.pop(f"{var}_ORIG", None)
        if original is not None:
            env[var] = original
        elif frozen:
            env.pop(var, None)
    return env


def run(cmd: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """subprocess.run с системным окружением."""
    kwargs.setdefault("env", system_env())
    return subprocess.run(cmd, **kwargs)  # noqa: S603 — команды фиксированные


def popen(cmd: Sequence[str], **kwargs: Any) -> subprocess.Popen:
    """subprocess.Popen с системным окружением."""
    kwargs.setdefault("env", system_env())
    return subprocess.Popen(cmd, **kwargs)  # noqa: S603 — команды фиксированные
