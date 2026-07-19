"""Встроенные языки интерфейса.

Русский — исходный (ключи перевода = русские строки из кода). Английский
поставляется в комплекте. Дополнительные языки можно ставить как плагины-
локали (см. discover_locales в plugins.manager и examples/locales/).
"""

from __future__ import annotations

from . import en


def builtin_locales() -> list[tuple[str, str, dict]]:
    """Список встроенных языков как (код, название, каталог переводов)."""
    return [(en.CODE, en.NAME, en.TRANSLATIONS)]
