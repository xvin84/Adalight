"""Гарантия полноты английского каталога: каждая строка, которую интерфейс
пропускает через tr(), обязана иметь перевод. Ловит забытые строки и опечатки
в ключах."""

import ast
import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

GUI = Path(__file__).resolve().parent.parent / "adalight" / "gui"


def _tr_literals() -> set[str]:
    """Строки из вызовов tr("литерал") во всех модулях GUI."""
    out: set[str] = set()
    for f in GUI.glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                fn = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if fn == "tr" and node.args:
                    a = node.args[0]
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        out.add(a.value)
    return out


def _required_keys() -> set[str]:
    keys = _tr_literals()
    # значения, оборачиваемые в месте использования: словари-метки, пресеты, шаблоны
    from adalight.config import PRESET_PROFILES
    from adalight.gui import main_window as mw

    for d in (mw._CORNER_LABELS, mw._DIRECTION_LABELS, mw._MODE_LABELS,
              mw._MUSIC_EFFECT_LABELS, mw._THEME_LABELS):
        keys |= set(d.values())
    # метки встроенных эффектов лампы — из реестра
    from adalight.effects import lamp_effects
    keys |= {spec.label for spec in lamp_effects() if spec.builtin}
    keys |= set(PRESET_PROFILES)
    for _label, title, intro in mw._REPORT_TEMPLATES.values():
        keys |= {title, intro}
    # метаданные встроенных плагинов показываются через tr()
    import importlib

    from adalight.plugins.manager import BUILTIN_MODULES

    for mod_name in BUILTIN_MODULES:
        plugin = importlib.import_module(mod_name).create_plugin()
        keys |= {getattr(plugin, "title", ""), getattr(plugin, "description", "")}
    keys.discard("")
    return keys


def test_english_catalog_is_complete():
    from adalight.locales import en

    required = _required_keys()
    missing = sorted(required - set(en.TRANSLATIONS))
    assert not missing, "нет перевода для строк:\n" + "\n".join(map(repr, missing))


def test_english_catalog_has_no_stale_keys():
    from adalight.locales import en

    required = _required_keys()
    stale = sorted(set(en.TRANSLATIONS) - required)
    assert not stale, "перевод есть, но строка нигде не используется:\n" + "\n".join(
        map(repr, stale)
    )


def test_placeholders_preserved():
    """{name}/{v}/… в переводе должны совпадать с исходником — иначе .format() падает."""
    from adalight.locales import en

    ph = re.compile(r"\{[^}]*\}")
    bad = [
        (ru, tr) for ru, tr in en.TRANSLATIONS.items()
        if set(ph.findall(ru)) != set(ph.findall(tr))
    ]
    assert not bad, "несовпадение плейсхолдеров:\n" + "\n".join(
        f"{ru!r} -> {tr!r}" for ru, tr in bad
    )
