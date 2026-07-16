import sys

import pytest

from adalight import autostart

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux-путь автозапуска")


@pytest.fixture
def xdg_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def test_enable_creates_desktop_file(xdg_home):
    assert not autostart.is_enabled()
    autostart.enable()
    desktop = xdg_home / "autostart" / "adalight.desktop"
    assert desktop.is_file()
    content = desktop.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content
    assert "--minimized" in content
    assert autostart.is_enabled()


def test_disable_removes_desktop_file(xdg_home):
    autostart.enable()
    autostart.disable()
    assert not autostart.is_enabled()
    autostart.disable()  # повторный вызов не падает


def test_launch_command_points_to_entry():
    cmd = autostart.launch_command()
    assert "--minimized" in cmd
    assert "main.py" in cmd or getattr(sys, "frozen", False)
