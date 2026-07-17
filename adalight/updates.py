"""Проверка и установка обновлений через GitHub Releases."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

RELEASES_API = "https://api.github.com/repos/xvin84/Adalight/releases/latest"
ASSET_NAMES = {"win32": "Adalight.exe", "linux": "Adalight-linux-x86_64"}
_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "Adalight"}


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.strip().lstrip("v").split("."))


def is_newer(candidate: str, current: str) -> bool:
    """True, если candidate новее current; мусорные версии считаются не новее."""
    try:
        return _version_tuple(candidate) > _version_tuple(current)
    except ValueError:
        return False


def fetch_latest(timeout: float = 6.0) -> tuple[str, str, str]:
    """(версия, URL страницы релиза, URL бинарника для этой ОС или '')."""
    req = urllib.request.Request(RELEASES_API, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    wanted = ASSET_NAMES.get(sys.platform, "")
    asset_url = next(
        (a["browser_download_url"] for a in data.get("assets", []) if a["name"] == wanted),
        "",
    )
    return data["tag_name"].lstrip("v"), data["html_url"], asset_url


def can_self_update() -> bool:
    """Автообновление возможно только для собранного бинарника (не из исходников)."""
    return bool(getattr(sys, "frozen", False)) and sys.platform in ASSET_NAMES


def staging_path() -> Path:
    """Куда качать новый бинарник: рядом с текущим (одна файловая система)."""
    current = Path(sys.executable)
    return current.with_name(current.name + ".new")


def download(url: str, dest: Path, progress: Callable[[int, int], None] | None = None) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "Adalight"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress is not None:
                progress(done, total)
    return dest


def _clean_env() -> dict[str, str]:
    """Окружение без служебных переменных PyInstaller.

    Их наследование заставляет новый exe искать временную папку старого
    процесса (уже удалённую) — классическая ошибка «Failed to load Python DLL
    ... Temp\\_MEI...\\python312.dll» после перезапуска.
    """
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("_PYI_") and k != "_MEIPASS2"
    }


def apply_and_restart(new_file: Path) -> None:
    """Заменяет текущий бинарник и запускает новую версию.

    Вызывающая сторона должна завершить приложение сразу после вызова.
    """
    current = Path(sys.executable).resolve()
    if sys.platform == "win32":
        # заменить работающий exe нельзя — bat ждёт, пока процесс отпустит файл,
        # и только потом запускает новую версию (фиксированная пауза давала гонку:
        # новый процесс стартовал, пока старый ещё чистил свой Temp\_MEI)
        script = current.with_name("adalight_update.bat")
        script.write_text(
            "@echo off\n"
            "set /a tries=0\n"
            ":retry\n"
            "set /a tries+=1\n"
            "timeout /t 1 /nobreak >nul\n"
            f'move /y "{new_file}" "{current}" >nul 2>&1\n'
            "if not errorlevel 1 goto done\n"
            "if %tries% lss 60 goto retry\n"
            ":done\n"
            f'start "" "{current}"\n'
            'del "%~f0"\n',
            encoding="mbcs",
        )
        subprocess.Popen(
            ["cmd", "/c", str(script)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
            env=_clean_env(),
        )
    else:
        os.replace(new_file, current)
        current.chmod(0o755)
        subprocess.Popen([str(current)], close_fds=True, env=_clean_env())
