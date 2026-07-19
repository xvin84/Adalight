import importlib.util
from pathlib import Path

from adalight.i18n import Translator


def test_source_language_is_identity():
    t = Translator()
    assert t.language == "ru"
    assert t.tr("Лампа") == "Лампа"  # русский исходник возвращается как есть


def test_register_and_translate_with_fallback():
    t = Translator()
    t.register("en", "English", {"Лампа": "Lamp"})
    t.set_language("en")
    assert t.tr("Лампа") == "Lamp"
    assert t.tr("Нет перевода") == "Нет перевода"  # откат к исходнику


def test_unknown_language_falls_back_to_source():
    t = Translator()
    t.set_language("de")  # не зарегистрирован
    assert t.language == "ru"


def test_source_cannot_be_overridden():
    t = Translator()
    t.register("ru", "Другой", {"Лампа": "Хаха"})
    assert t.tr("Лампа") == "Лампа"


def test_available_lists_source_first():
    t = Translator()
    t.register("en", "English", {})
    t.register("cs", "Čeština", {})
    codes = [c for c, _ in t.available()]
    assert codes[0] == "ru"
    assert set(codes) == {"ru", "en", "cs"}


def test_example_english_locale_contract():
    path = (
        Path(__file__).resolve().parent.parent / "examples" / "locales" / "en.py"
    )
    spec = importlib.util.spec_from_file_location("example_en_locale", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loc = module.create_locale()
    assert loc.code == "en" and loc.name == "English"
    assert loc.translations["Режим"] == "Mode"

    t = Translator()
    t.register(loc.code, loc.name, loc.translations)
    t.set_language("en")
    assert t.tr("Система") == "System"
