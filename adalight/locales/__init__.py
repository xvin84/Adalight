"""Встроенные языки интерфейса.

Русский — исходный (ключи перевода = русские строки из кода). Английский идёт
в комплекте, но через тот же контракт `create_locale()`, что и языки-плагины:
«всё есть плагин, базовый — встроен». Дополнительные языки ставятся как
плагины-локали (см. discover_locales в plugins.manager и examples/locales/).
"""

from __future__ import annotations

from . import en

# модули встроенных локалей (каждый экспортирует create_locale())
_BUILTIN_LOCALE_MODULES = (en,)


def builtin_locales() -> list[tuple[str, str, dict]]:
    """Список встроенных языков как (код, название, каталог переводов)."""
    out: list[tuple[str, str, dict]] = []
    for module in _BUILTIN_LOCALE_MODULES:
        loc = module.create_locale()
        out.append((str(loc.code), str(loc.name), dict(loc.translations)))
    return out
