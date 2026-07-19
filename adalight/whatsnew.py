"""«Что нового»: разбор CHANGELOG.md и выбор секций между версиями.

Единственный источник — CHANGELOG.md (кладётся в сборку). После обновления
приложение показывает все секции с версией в диапазоне (последняя_показанная,
текущая], даже если пользователь прыгнул через несколько версий. Модуль
не зависит от Qt — легко покрывается тестами.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .updates import is_newer

# любой заголовок «## [версия]» — граница секции; несемвер-версии (0.9.x)
# станут отдельными записями, но is_newer исключит их из выборки диапазона
_HEADER = re.compile(r"^##\s*\[([^\]]+)\]")


def _base_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def changelog_files() -> dict[str, str]:
    """{код языка: путь} — CHANGELOG.md (ru) + CHANGELOG.<код>.md."""
    base = _base_dir()
    files: dict[str, str] = {}
    if (base / "CHANGELOG.md").is_file():
        files["ru"] = str(base / "CHANGELOG.md")
    for path in base.glob("CHANGELOG.*.md"):
        code = path.name[len("CHANGELOG."):-len(".md")]
        files[code] = str(path)
    return files


def available_changelog_langs() -> list[str]:
    return list(changelog_files())


def parse_changelog(text: str) -> list[tuple[str, str]]:
    """[(версия, тело-markdown), …] в порядке файла (новые сверху)."""
    entries: list[tuple[str, str]] = []
    version: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        match = _HEADER.match(line)
        if match:
            if version is not None:
                entries.append((version, "\n".join(body).strip()))
            version = match.group(1)
            body = []
        elif version is not None:
            body.append(line)
    if version is not None:
        entries.append((version, "\n".join(body).strip()))
    return entries


def _semver(v: str) -> tuple[int, int, int] | None:
    parts = v.split(".")
    if len(parts) != 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def notes_between(
    entries: list[tuple[str, str]], last: str, current: str
) -> list[tuple[str, str]]:
    """Секции с версией строго новее last и не новее current (по убыванию версии).

    Несемвер-версии (например 0.9.x) в диапазон не попадают.
    """
    picked = [
        (ver, body)
        for ver, body in entries
        if _semver(ver) is not None
        and (not last or is_newer(ver, last))
        and not is_newer(ver, current)
    ]
    picked.sort(key=lambda e: _semver(e[0]), reverse=True)
    return picked


def to_markdown(notes: list[tuple[str, str]]) -> str:
    """Собрать секции в один markdown с заголовком версии перед каждой."""
    return "\n\n".join(f"## {ver}\n\n{body}" for ver, body in notes)


def update_notes(
    last: str, current: str, lang: str = "ru", text: str | None = None
) -> str:
    """Готовый markdown изменений для окна «Что нового» ('' — показывать нечего).

    Берётся changelog на языке lang (откат на русский, если для языка его нет).
    last пусто (обновление с версии до появления маркера, прошлую версию мы не
    знаем) → показываем всю историю до current, чтобы прыжок через версии не
    съедал изменения.
    """
    if text is None:
        files = changelog_files()
        path = files.get(lang) or files.get("ru")
        if path is None:
            return ""
        text = Path(path).read_text(encoding="utf-8")
    return to_markdown(notes_between(parse_changelog(text), last, current))
