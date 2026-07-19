"""Каталог плагинов: официальные и от сообщества, установка в один клик.

Индекс — plugins-index.json в основном репозитории; каждая запись указывает
на raw-файл плагина. Установка = скачивание .py в папку плагинов.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .manager import plugins_dir

INDEX_URL = "https://raw.githubusercontent.com/xvin84/Adalight/main/plugins-index.json"
_REQUIRED = ("name", "title", "description", "kind", "url")


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    title: str
    description: str
    kind: str  # official | community
    url: str
    author: str = ""
    version: str = ""


def parse_index(data: dict) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    for i, raw in enumerate(data.get("plugins", []), start=1):
        missing = [key for key in _REQUIRED if not raw.get(key)]
        if missing:
            raise ValueError(f"Запись каталога {i}: нет полей {', '.join(missing)}")
        if raw["kind"] not in ("official", "community"):
            raise ValueError(f"Запись каталога {i}: неверный kind {raw['kind']!r}")
        entries.append(
            CatalogEntry(
                name=str(raw["name"]),
                title=str(raw["title"]),
                description=str(raw["description"]),
                kind=str(raw["kind"]),
                url=str(raw["url"]),
                author=str(raw.get("author", "")),
                version=str(raw.get("version", "")),
            )
        )
    return entries


def _http_fetch(url: str, timeout: float = 10.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Adalight"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_catalog(fetcher: Callable[[str], bytes] = _http_fetch) -> list[CatalogEntry]:
    return parse_index(json.loads(fetcher(INDEX_URL)))


def is_installed(name: str, base: Path | None = None) -> bool:
    return ((base or plugins_dir()) / f"{name}.py").is_file()


def install(
    entry: CatalogEntry,
    base: Path | None = None,
    fetcher: Callable[[str], bytes] = _http_fetch,
) -> Path:
    """Скачивает плагин в папку плагинов; повторная установка = обновление."""
    data = fetcher(entry.url)
    if b"create_plugin" not in data and b"create_locale" not in data:
        raise ValueError(
            f"Файл по адресу {entry.url} не похож на плагин Adalight "
            "(нет функции create_plugin или create_locale)"
        )
    target_dir = base or plugins_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{entry.name}.py"
    target.write_bytes(data)
    return target
