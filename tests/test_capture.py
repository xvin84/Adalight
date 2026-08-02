import pytest

from adalight import capture
from adalight.capture import CaptureError, create_backend
from adalight.config import Config


class _FakeBackend:
    width = 10
    height = 10
    supports_bands = False
    fallback_reason = None

    def get_frame(self):
        return None


def test_create_backend_by_id_and_unknown():
    hits = []
    capture.register_capture_source(
        "faketest", "Fake", lambda cfg: hits.append(cfg) or _FakeBackend(),
        platforms=("any",), priority=1, source="t_by_id",
    )
    try:
        backend = create_backend(Config(backend="faketest"))
        assert isinstance(backend, _FakeBackend) and hits
        with pytest.raises(CaptureError):
            create_backend(Config(backend="no_such_source_xyz"))
    finally:
        capture.unregister_source("t_by_id")
    assert capture.capture_source("faketest") is None


def test_auto_picks_by_priority_and_falls_back():
    def failing(cfg):
        raise RuntimeError("нет устройства")

    capture.register_capture_source(
        "auto_fail", "Fail", failing, platforms=("any",), priority=1, source="t_auto",
    )
    capture.register_capture_source(
        "auto_ok", "Ok", lambda cfg: _FakeBackend(),
        platforms=("any",), priority=2, source="t_auto",
    )
    try:
        backend = create_backend(Config(backend="auto"))
        # приоритетный источник упал — взяли следующий, причина зафиксирована
        assert isinstance(backend, _FakeBackend)
        assert backend.fallback_reason and "auto_fail" in backend.fallback_reason
    finally:
        capture.unregister_source("t_auto")


def test_capture_mod_activate_deactivate():
    from test_plugins import _empty_manager

    from adalight.plugins.builtin import capture as capture_mod
    from adalight.plugins.manager import LoadedPlugin

    capture.unregister_source("capture")
    assert capture.capture_source("mss") is None

    manager = _empty_manager()
    loaded = LoadedPlugin(
        capture_mod.create_plugin(), "capture", "Захват экрана", "", base=True
    )
    manager.plugins = [loaded]

    manager.apply({})  # base=True → активируется, регистрирует источники
    assert loaded.running and capture.capture_source("mss") is not None

    manager.apply({"capture": {"enabled": False}})  # выключаем
    assert not loaded.running and capture.capture_source("mss") is None


def test_hyprland_monitors_reports_stderr(monkeypatch):
    """Причина падения hyprctl должна попадать в текст ошибки, а не теряться."""
    import subprocess

    from adalight.capture import wayland

    def fake_run(cmd, **kwargs):
        stderr = "hyprctl: libstdc++.so.6: version `GLIBCXX_3.4.35' not found\n"
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=stderr)

    monkeypatch.setattr(wayland.subproc, "run", fake_run)
    with pytest.raises(CaptureError, match="GLIBCXX_3.4.35"):
        wayland.hyprland_monitors()


def test_hyprland_monitors_missing_binary(monkeypatch):
    from adalight.capture import wayland

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(wayland.subproc, "run", fake_run)
    with pytest.raises(CaptureError, match="hyprctl не найден"):
        wayland.hyprland_monitors()


def test_resolve_output_accepts_label_from_old_config(monkeypatch):
    """Ярлык, сохранённый старым GUI, должен разрешаться в имя монитора."""
    from adalight.capture import wayland

    monkeypatch.setattr(
        wayland, "hyprland_monitors",
        lambda: [{"name": "eDP-1", "width": 2560, "height": 1600},
                 {"name": "HDMI-A-1", "width": 1920, "height": 1080}],
    )
    assert wayland.resolve_output(Config(output="HDMI-A-1 (1920x1080)")) == (
        "HDMI-A-1", 1920, 1080
    )
    assert wayland.resolve_output(Config(output="HDMI-A-1")) == ("HDMI-A-1", 1920, 1080)
    with pytest.raises(CaptureError, match="не найден"):
        wayland.resolve_output(Config(output="DP-9"))
