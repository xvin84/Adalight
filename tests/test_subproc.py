import subprocess
import sys

import pytest

from adalight import subproc


@pytest.fixture
def frozen(monkeypatch):
    """Притвориться собранным бинарником PyInstaller."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)


def test_system_env_drops_pyinstaller_vars(monkeypatch, frozen):
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "/tmp/_MEI42")
    monkeypatch.setenv("_MEIPASS2", "/tmp/_MEI42")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = subproc.system_env()

    assert "_PYI_APPLICATION_HOME_DIR" not in env
    assert "_MEIPASS2" not in env
    assert env["PATH"] == "/usr/bin"


def test_system_env_removes_bundle_library_path(monkeypatch, frozen):
    # LD_LIBRARY_PATH_ORIG нет — значит переменной не было до запуска бандла,
    # и путь к _MEI не должен утечь в hyprctl/grim (иначе чужой libstdc++)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI42")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)

    assert "LD_LIBRARY_PATH" not in subproc.system_env()


def test_system_env_restores_original_library_path(monkeypatch, frozen):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI42:/opt/mylibs")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/opt/mylibs")

    env = subproc.system_env()

    assert env["LD_LIBRARY_PATH"] == "/opt/mylibs"
    assert "LD_LIBRARY_PATH_ORIG" not in env


def test_system_env_keeps_library_path_when_not_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/mylibs")

    assert subproc.system_env()["LD_LIBRARY_PATH"] == "/opt/mylibs"


def test_run_and_popen_pass_clean_env(monkeypatch, frozen):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI42")
    # маркер только из ASCII: консоль Windows роняет дочерний процесс на кириллице
    code = "import os; print(os.environ.get('LD_LIBRARY_PATH', 'unset'))"

    done = subproc.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.stdout.strip() == "unset"

    proc = subproc.popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert proc.communicate()[0].strip() == "unset"
