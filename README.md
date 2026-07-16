# Adalight

Фоновая подсветка (ambilight) для LED-ленты по протоколу **Adalight**: программа
захватывает экран, вычисляет цвета по краям и отправляет их на Arduino/ESP по serial.

Работает на **Windows** (DXGI Desktop Duplication через `dxcam`, fallback — `mss`)
и **Linux/Wayland** (Hyprland/wlroots: `wf-recorder`, fallback — `grim`).

## Возможности

- Графический интерфейс (PySide6): все настройки в одном окне, живой предпросмотр
  раскладки диодов, иконка в трее.
- Настройка: serial-порт и скорость, **порядок каналов** (RGB/GRB/BGR/…),
  количество диодов на каждой стороне, стартовый угол и направление ленты,
  выбор монитора, FPS, гамма/яркость/насыщенность/сглаживание.
- Тестовые режимы для калибровки: заливка сторон цветами и «бегущий диод».
- CLI для headless-запуска (например, из автозагрузки).
- Конфиг хранится в JSON: `%APPDATA%\adalight\config.json` (Windows)
  или `~/.config/adalight/config.json` (Linux).

## Запуск из исходников

Нужен [uv](https://docs.astral.sh/uv/):

```bash
uv sync

# GUI
uv run main.py

# Headless-подсветка и сервисные режимы
uv run main.py --live
uv run main.py --sides          # тест: верх=красный, право=зелёный, низ=синий, лево=жёлтый
uv run main.py --chase          # тест: бегущий диод
uv run main.py --off            # погасить ленту
uv run main.py --list-monitors
uv run main.py --list-ports
```

## Сборка exe для Windows

```bash
uv sync --dev
uv run pyinstaller --noconfirm --onefile --windowed --name Adalight --collect-submodules comtypes main.py
# результат: dist/Adalight.exe
```

## Релизы (CI/CD)

- **CI** (`.github/workflows/ci.yml`): на каждый push/PR — ruff + pytest.
- **Release** (`.github/workflows/release.yml`): при пуше тега `v*` собирается
  `Adalight.exe` под Windows и публикуется GitHub Release. Версия тега должна
  совпадать с версией в `pyproject.toml`.

Выпуск новой версии:

```bash
# 1. поднять version в pyproject.toml и adalight/__init__.py, закоммитить
# 2. затем:
git tag v0.2.0
git push origin v0.2.0
```

## Протокол

Классический Adalight: заголовок `"Ada" + count_hi + count_lo + (hi^lo^0x55)`,
далее по 3 байта на диод в порядке каналов, заданном в настройках
(WS2812 обычно ожидает GRB).

## Структура

```
adalight/
  config.py        # dataclass конфигурации + JSON load/save
  geometry.py      # раскладка диодов и зоны захвата
  device.py        # протокол Adalight, LUT-гамма, порядок каналов
  engine.py        # цикл захват->обработка->отправка (без Qt)
  capture/         # бэкенды: dxcam (Windows), mss, wf-recorder, grim
  cli.py           # headless-режимы
  gui/             # PySide6: главное окно, предпросмотр, трей
main.py            # входная точка: GUI без аргументов, иначе CLI
```
