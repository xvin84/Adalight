"""Автозапуск при входе в систему: реестр на Windows, XDG autostart на Linux."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Adalight"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command() -> str:
    """Команда запуска GUI свёрнутым в трей (для exe и для запуска из исходников)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{sys.executable}" "{main_py}" --minimized'


def is_supported() -> bool:
    return sys.platform in ("win32", "linux")


def _desktop_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / "adalight.desktop"


def is_enabled() -> bool:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                winreg.QueryValueEx(key, APP_NAME)
            return True
        except OSError:
            return False
    return _desktop_path().is_file()


def enable() -> None:
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_command())
        return
    p = _desktop_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Exec={launch_command()}\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )


def disable() -> None:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, APP_NAME)
        except OSError:
            pass
        return
    _desktop_path().unlink(missing_ok=True)
