"""Точка входа Adalight.

Без аргументов запускается GUI; --minimized запускает GUI свёрнутым в трей
с включённой подсветкой (используется автозапуском). Остальные аргументы
уходят в CLI (--live, --sides, --chase, --off, --list-monitors, ...).
"""

import sys


def main() -> int:
    args = sys.argv[1:]
    if not args or args == ["--minimized"]:
        from adalight.gui import run

        return run(minimized=bool(args))
    from adalight.cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
