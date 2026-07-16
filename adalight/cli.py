"""CLI-режимы (headless): подсветка, тесты, выключение ленты."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .capture import CaptureError, list_outputs
from .config import Config
from .device import DeviceError, list_serial_ports
from .engine import Engine


def _print_outputs() -> None:
    outputs = list_outputs()
    if not outputs:
        print("Мониторы не найдены (или утилиты перечисления недоступны).")
        return
    print("Доступные мониторы:")
    for value, label in outputs:
        print(f"  {value:12s} {label}")


def _print_ports() -> None:
    ports = list_serial_ports()
    if not ports:
        print("Serial-порты не найдены.")
        return
    print("Доступные порты:")
    for device, desc in ports:
        print(f"  {device:16s} {desc}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="adalight",
        description="Adalight ambilight. Без аргументов запускается графический интерфейс.",
    )
    ap.add_argument("--version", action="version", version=f"adalight {__version__}")
    ap.add_argument("--live", action="store_true", help="Запустить подсветку без GUI")
    ap.add_argument("--lamp", action="store_true", help="Режим «лампа» без GUI")
    ap.add_argument("--music", action="store_true", help="Цветомузыка без GUI")
    ap.add_argument("--sides", action="store_true", help="Тест: заливка сторон разными цветами")
    ap.add_argument("--chase", action="store_true", help="Тест: бегущий диод")
    ap.add_argument("--off", action="store_true", help="Погасить ленту и выйти")
    ap.add_argument("--list-monitors", action="store_true", help="Показать доступные мониторы")
    ap.add_argument("--list-ports", action="store_true", help="Показать доступные serial-порты")
    ap.add_argument("--port", help="Переопределить serial-порт из конфига")
    ap.add_argument("--output", help="Переопределить монитор из конфига")
    args = ap.parse_args(argv)

    if args.list_monitors:
        _print_outputs()
        return 0
    if args.list_ports:
        _print_ports()
        return 0

    cfg = Config.load()
    if args.port:
        cfg.port = args.port
    if args.output:
        cfg.output = args.output

    if args.off:
        mode = "off"
    elif args.chase:
        mode = "chase"
    elif args.sides:
        mode = "sides"
    elif args.lamp:
        mode = "lamp"
    elif args.music:
        mode = "music"
    else:
        mode = "live"

    try:
        engine = Engine(cfg, on_fps=lambda f: print(f"\r~{f:.1f} fps   ", end="", flush=True))
    except ValueError as e:
        print(f"Ошибка конфигурации: {e}", file=sys.stderr)
        return 2

    if mode == "live":
        print(f"Запуск: {cfg.total_leds} диодов, порт {cfg.port}, бэкенд {cfg.backend}")
    print("Ctrl+C — выход.")

    try:
        engine.run(mode)
    except KeyboardInterrupt:
        print("\nЗавершение работы...")
    except (DeviceError, CaptureError) as e:
        print(f"\nОшибка: {e}", file=sys.stderr)
        return 1

    if mode == "off":
        print("Лента погашена.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
