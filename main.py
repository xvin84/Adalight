"""Точка входа Adalight.

Без аргументов запускается GUI; любые аргументы уходят в CLI
(--live, --sides, --chase, --off, --list-monitors, --list-ports, ...).
"""

import sys


def main() -> int:
    if len(sys.argv) > 1:
        from adalight.cli import main as cli_main

        return cli_main()
    from adalight.gui import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
