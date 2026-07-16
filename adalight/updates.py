"""Проверка новых версий через GitHub Releases API."""

from __future__ import annotations

import json
import urllib.request

RELEASES_API = "https://api.github.com/repos/xvin84/Adalight/releases/latest"


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.strip().lstrip("v").split("."))


def is_newer(candidate: str, current: str) -> bool:
    """True, если candidate новее current; мусорные версии считаются не новее."""
    try:
        return _version_tuple(candidate) > _version_tuple(current)
    except ValueError:
        return False


def fetch_latest(timeout: float = 6.0) -> tuple[str, str]:
    """(версия последнего релиза, URL страницы релиза). Бросает OSError/ValueError."""
    req = urllib.request.Request(
        RELEASES_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Adalight"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    return data["tag_name"].lstrip("v"), data["html_url"]
