"""Локализация: перевод строк-исходников на активный язык.

Исходный язык — русский: ключами перевода служат сами русские строки из кода
(`tr("Лампа")`). Язык — это каталог `{русская строка: перевод}`; отсутствующий
ключ откатывается к русскому исходнику. Языки можно поставлять плагинами-
локалями (модуль с `create_locale()`), поэтому «язык — это тоже плагин».

Модуль намеренно не зависит от Qt: ядро и CLI пользуются им напрямую.
"""

from __future__ import annotations

import threading

SOURCE_LANGUAGE = ("ru", "Русский")


class Translator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._language = SOURCE_LANGUAGE[0]
        self._catalogs: dict[str, dict[str, str]] = {}
        self._names: dict[str, str] = {SOURCE_LANGUAGE[0]: SOURCE_LANGUAGE[1]}

    def register(self, code: str, name: str, mapping: dict[str, str]) -> None:
        """Добавить/дополнить язык. Русский исходник переопределять нельзя."""
        if code == SOURCE_LANGUAGE[0]:
            return
        with self._lock:
            self._names[code] = name
            self._catalogs.setdefault(code, {}).update(mapping or {})

    def set_language(self, code: str) -> None:
        with self._lock:
            self._language = code if code in self._names else SOURCE_LANGUAGE[0]

    @property
    def language(self) -> str:
        return self._language

    def available(self) -> list[tuple[str, str]]:
        """Список (код, название): исходный русский первым, остальные по алфавиту."""
        with self._lock:
            extras = sorted(
                (c for c in self._names if c != SOURCE_LANGUAGE[0]),
                key=lambda c: self._names[c].lower(),
            )
            return [SOURCE_LANGUAGE] + [(c, self._names[c]) for c in extras]

    def tr(self, text: str) -> str:
        if self._language == SOURCE_LANGUAGE[0]:
            return text
        return self._catalogs.get(self._language, {}).get(text, text)


_translator = Translator()


def tr(text: str) -> str:
    return _translator.tr(text)


def set_language(code: str) -> None:
    _translator.set_language(code)


def register_language(code: str, name: str, mapping: dict[str, str]) -> None:
    _translator.register(code, name, mapping)


def available_languages() -> list[tuple[str, str]]:
    return _translator.available()


def current_language() -> str:
    return _translator.language
