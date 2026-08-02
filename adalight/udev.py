"""Linux: доступ к serial-порту без ручной правки групп — через udev-правило.

Ключевой момент — TAG+="uaccess": права на устройство выдаёт systemd-logind
текущему пользователю графической сессии, без добавления в группы
(dialout/uucp) и без перелогина. Приложение умеет проверить, установлено ли
правило, и поставить его одной кнопкой (pkexec) либо показать команду для
ручного выполнения. На дистрибутивах без logind остаётся запасной путь через
группу — см. group_fallback_hint().

Копия правила лежит в packaging/99-adalight.rules (для ручной установки из
релиза); tests/test_udev.py следит, чтобы содержимое не разъехалось.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import subproc

RULES_FILENAME = "99-adalight.rules"
RULES_PATH = Path("/etc/udev/rules.d") / RULES_FILENAME

# Производители USB-serial мостов из комплектных и альтернативных плат:
# CH340/CH9102 (1a86), CP2102 (10c4), FTDI FT232 (0403), ESP32 с родным USB (303a).
RULES_CONTENT = """\
# Adalight: доступ пользователя графической сессии к USB-serial платам.
# TAG+="uaccess" — права выдаёт systemd-logind, группы и перелогин не нужны.
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", MODE="0660", TAG+="uaccess"
"""

RELOAD_COMMAND = "sudo udevadm control --reload-rules && sudo udevadm trigger"


def is_supported() -> bool:
    return sys.platform.startswith("linux")


def is_rule_installed(path: Path = RULES_PATH) -> bool:
    return path.is_file()


def manual_command(path: Path = RULES_PATH) -> str:
    """Команда для ручной установки правила (скопировать в терминал)."""
    return (
        f"sudo tee {path} >/dev/null <<'EOF'\n{RULES_CONTENT}EOF\n{RELOAD_COMMAND}"
    )


def group_fallback_hint() -> str:
    """Запасной путь для систем без systemd-logind: группа dialout/uucp."""
    return "sudo usermod -aG dialout $USER   # на Arch — uucp; затем перелогин"


def install_rule(path: Path = RULES_PATH) -> tuple[bool, str]:
    """Установить правило с запросом прав через pkexec и сразу применить его.

    Возвращает (успех, сообщение об ошибке). После установки правило действует
    со следующего подключения устройства — плату нужно передёрнуть по USB.
    """
    fd, tmp = tempfile.mkstemp(suffix=".rules", text=True)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(RULES_CONTENT)
        try:
            proc = subproc.run(
                [
                    "pkexec", "sh", "-c",
                    'install -D -m 0644 "$1" "$2" '
                    "&& udevadm control --reload-rules && udevadm trigger",
                    "sh", tmp, str(path),
                ],
                capture_output=True,
                text=True,
                timeout=180,  # pkexec ждёт ввода пароля
            )
        except FileNotFoundError:
            return False, "pkexec не найден — выполните команду вручную"
        except subprocess.TimeoutExpired:
            return False, "не дождались авторизации pkexec"
    finally:
        os.unlink(tmp)
    if proc.returncode == 0:
        return True, ""
    if proc.returncode in (126, 127):  # отказ в авторизации / диалог закрыт
        return False, "авторизация отклонена"
    return False, (proc.stderr.strip() or proc.stdout.strip()
                   or f"код возврата {proc.returncode}")
