#!/usr/bin/env python3
"""Собирает тело GitHub-релиза: «что нового» + описание + возможности, EN → RU.

Источник «что нового» — секция текущей версии из CHANGELOG.en.md / CHANGELOG.md.
Описание и список возможностей — краткая выжимка ниже (полный список — в README).
Запуск: python scripts/release_notes.py [версия] > RELEASE_NOTES.md
Без аргумента версия берётся из pyproject.toml.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BETA_EN = (
    "> ⚠️ **Beta.** Adalight is pre-1.0 — a few rough edges are expected. "
    "Please report bugs and ideas in the [issues](https://github.com/xvin84/Adalight/issues)."
)
BETA_RU = (
    "> ⚠️ **Бета-версия.** Adalight ещё до 1.0 — возможны шероховатости. "
    "Пишите об ошибках и идеях в [issues](https://github.com/xvin84/Adalight/issues)."
)

ABOUT_EN = (
    "Screen-edge ambient lighting (ambilight) for an LED strip behind your "
    "monitor: the app captures the screen, averages the colors along the edges "
    "and streams them to an Arduino/ESP over the classic **Adalight** protocol. "
    "Runs on **Windows** and **Linux/Wayland** with a Qt GUI and a tray icon."
)
ABOUT_RU = (
    "Фоновая подсветка (ambilight) для LED-ленты за монитором: приложение "
    "захватывает экран, усредняет цвета по краям и шлёт их на Arduino/ESP по "
    "классическому протоколу **Adalight**. Работает на **Windows** и "
    "**Linux/Wayland**, есть графический интерфейс на Qt и иконка в трее."
)

FEATURES_EN = [
    "**Screen capture** with autodetected backend (dxcam/bettercam/mss on "
    "Windows, wf-recorder/grim on Wayland).",
    "**Lamp mode**: solid / gradient / rainbows / breathing / fireplace / comet "
    "/ aurora / starry sky — works without capture.",
    "**Music mode**: system audio drives the LEDs (spectrum, bass pulse, bass "
    "waves, beat flashes).",
    "**Smart port picker**: only boards (Arduino/ESP) and USB devices are shown "
    "by default, with friendly labels; “Show all ports” reveals the rest.",
    "**Color pipeline**: gamma / brightness / saturation / color temperature / "
    "white balance / shadow cut-off; brightness schedule and adaptive brightness.",
    "**Transports**: serial (Adalight over USB) and WLED over Wi-Fi (beta).",
    "**Everything is a mod**: effects, music, capture, transports and "
    "notifications are built-in mods; plugins extend them via a single contract "
    "and an event bus.",
    "**Notification flashes**, presets (Movie/Game/Work), profiles, autostart, "
    "auto-update, first-run wizard, RU/EN UI, dark/light themes.",
]
FEATURES_RU = [
    "**Захват экрана** с авто-выбором бэкенда (dxcam/bettercam/mss на Windows, "
    "wf-recorder/grim на Wayland).",
    "**Режим «Лампа»**: цвет / градиент / радуги / дыхание / камин / комета / "
    "северное сияние / звёздное небо — работает без захвата.",
    "**Цветомузыка**: звук системы управляет лентой (спектр, пульс от баса, "
    "волны от баса, вспышки на битах).",
    "**Умный выбор порта**: по умолчанию показаны только платы (Arduino/ESP) и "
    "USB-устройства с понятными ярлыками; «Показать все порты» открывает остальные.",
    "**Конвейер цвета**: гамма / яркость / насыщенность / температура / баланс "
    "белого / отсечка теней; расписание яркости и адаптивная яркость.",
    "**Транспорты**: serial (Adalight по USB) и WLED по Wi-Fi (beta).",
    "**Всё есть мод**: эффекты, музыка, захват, транспорты и уведомления — "
    "встроенные моды; плагины расширяют их через единый контракт и событийную шину.",
    "**Вспышки уведомлений**, пресеты (Кино/Игра/Работа), профили, автозапуск, "
    "автообновление, мастер первого запуска, RU/EN интерфейс, тёмная/светлая темы.",
]

DOWNLOAD_EN = (
    "**Download:** Windows — `Adalight-Setup.exe` (installer, recommended) or "
    "portable `Adalight.exe`; Linux — `Adalight-linux-x86_64` "
    "(`chmod +x`, Wayland capture needs `wf-recorder`)."
)
DOWNLOAD_RU = (
    "**Скачать:** Windows — `Adalight-Setup.exe` (установщик, рекомендуется) или "
    "переносимый `Adalight.exe`; Linux — `Adalight-linux-x86_64` "
    "(`chmod +x`, для захвата на Wayland нужен `wf-recorder`)."
)

_FW_TREE = "https://github.com/xvin84/Adalight/tree/main/firmware"
FIRMWARE_EN = (
    f"Board firmware (Arduino/ESP) is in [`firmware/`]({_FW_TREE}) "
    "— a reference Adalight sketch by **AlexGyver** "
    "(<https://alexgyver.ru/arduino_ambilight/>), included with attribution."
)
FIRMWARE_RU = (
    f"Прошивка для платы (Arduino/ESP) — в [`firmware/`]({_FW_TREE}): "
    "эталонный скетч Adalight авторства **AlexGyver** "
    "(<https://alexgyver.ru/arduino_ambilight/>), добавлен с указанием авторства."
)


def project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def changelog_section(path: Path, version: str) -> str:
    """Содержимое блока `## [version] — дата` до следующего `## ` (без заголовка)."""
    text = path.read_text(encoding="utf-8")
    # экранируем версию, ловим весь блок до следующего заголовка второго уровня
    pat = re.compile(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pat.search(text)
    return m.group(1).strip() if m else "_(нет записи в журнале изменений)_"


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {x}" for x in items)


def build(version: str) -> str:
    whats_new_en = changelog_section(ROOT / "CHANGELOG.en.md", version)
    whats_new_ru = changelog_section(ROOT / "CHANGELOG.md", version)
    tag = f"v{version}"
    return "\n".join([
        BETA_EN,
        "",
        "## 🇬🇧 English",
        "",
        f"### What's new in {tag}",
        whats_new_en,
        "",
        "### What is Adalight",
        ABOUT_EN,
        "",
        "### Key features",
        _bullets(FEATURES_EN),
        "",
        "_Full feature list and docs — see the "
        "[README](https://github.com/xvin84/Adalight#readme)._",
        "",
        DOWNLOAD_EN,
        "",
        FIRMWARE_EN,
        "",
        "---",
        "",
        BETA_RU,
        "",
        "## 🇷🇺 Русский",
        "",
        f"### Что нового в {tag}",
        whats_new_ru,
        "",
        "### Что такое Adalight",
        ABOUT_RU,
        "",
        "### Основные возможности",
        _bullets(FEATURES_RU),
        "",
        "_Полный список возможностей и документация — в "
        "[README](https://github.com/xvin84/Adalight/blob/main/README.ru.md)._",
        "",
        DOWNLOAD_RU,
        "",
        FIRMWARE_RU,
        "",
    ])


def main(argv: list[str]) -> int:
    version = argv[1] if len(argv) > 1 else project_version()
    sys.stdout.write(build(version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
