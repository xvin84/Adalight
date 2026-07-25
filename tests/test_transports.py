"""Реестр транспортов и жизненный цикл встроенного мода «Транспорты»."""

from adalight import transports
from adalight.config import Config


def test_register_and_make_transport():
    class DummyTransport:
        def __init__(self, cfg):
            self.cfg = cfg

    transports.register_transport(
        "dummy", "Dummy", DummyTransport, needs_network=True, source="t_reg",
    )
    try:
        spec = transports.transport("dummy")
        assert spec is not None and spec.needs_network and not spec.needs_serial
        obj = transports.make_transport("dummy", Config())
        assert isinstance(obj, DummyTransport)
        assert transports.make_transport("nope", Config()) is None
    finally:
        transports.unregister_source("t_reg")
    assert transports.transport("dummy") is None


def test_transports_mod_activate_deactivate():
    from test_plugins import _empty_manager

    from adalight.plugins.builtin import transports as transports_mod
    from adalight.plugins.manager import LoadedPlugin

    transports.unregister_source("transports")
    assert transports.transport("serial") is None

    manager = _empty_manager()
    loaded = LoadedPlugin(
        transports_mod.create_plugin(), "transports", "Транспорты", "", base=True
    )
    manager.plugins = [loaded]

    manager.apply({})  # base=True → активируется, регистрирует транспорты
    assert loaded.running
    assert transports.transport("serial") is not None
    assert transports.transport("wled") is not None

    manager.apply({"transports": {"enabled": False}})  # выключаем
    assert not loaded.running
    assert transports.transport("serial") is None


def test_device_without_transport_mod_raises():
    from adalight.device import AdalightDevice, DeviceError

    transports.unregister_source("transports")
    try:
        dev = AdalightDevice(Config(transport="serial"))
        try:
            dev.connect()
            raise AssertionError("ожидали DeviceError без мода «Транспорты»")
        except DeviceError:
            pass
    finally:
        # вернуть транспорты для следующих тестов (autouse-фикстура тоже это делает)
        from adalight.plugins.builtin.transports import TRANSPORTS
        for tid, label, factory, flags in TRANSPORTS:
            transports.register_transport(
                tid, label, factory, source="transports", **flags
            )


# ── serial: ошибка прав (EACCES) и фолбэк при смене номера порта ──────────


def test_is_access_denied_variants():
    from adalight.plugins.builtin.transports import _is_access_denied

    assert _is_access_denied(PermissionError(13, "Permission denied"))
    assert _is_access_denied(Exception("[Errno 13] Permission denied: '/dev/ttyUSB1'"))
    assert _is_access_denied(Exception("Access is denied."))
    assert not _is_access_denied(Exception("could not open port: FileNotFoundError"))


def test_serial_access_denied_raises_port_access_error(monkeypatch):
    """EACCES — отдельная ошибка: «нет прав», а не «плата не найдена»."""
    import serial as pyserial

    from adalight.device import PortAccessError
    from adalight.plugins.builtin.transports import SerialTransport

    def denied(*args, **kwargs):
        raise pyserial.SerialException(
            "[Errno 13] could not open port /dev/ttyUSB1: "
            "[Errno 13] Permission denied: '/dev/ttyUSB1'"
        )

    monkeypatch.setattr(pyserial, "Serial", denied)
    transport = SerialTransport(Config(port="/dev/ttyUSB1"))
    try:
        transport.connect()
        raise AssertionError("ожидали PortAccessError")
    except PortAccessError as e:
        assert "прав" in str(e)


def test_serial_falls_back_to_single_board(monkeypatch):
    """Порт сменил номер после переподключения — открываем единственную плату."""
    import serial as pyserial

    from adalight.device import PortInfo
    from adalight.plugins.builtin import transports as tmod

    opened = []

    class FakePySerial:
        def __init__(self, port, baud, timeout=None):
            if port == "/dev/ttyUSB0":
                raise pyserial.SerialException(
                    "could not open port /dev/ttyUSB0: FileNotFoundError"
                )
            opened.append(port)

        def reset_input_buffer(self):
            pass

    fallback = PortInfo(
        device="/dev/ttyUSB1", description="", vid=0x1A86, pid=0x7523,
        is_usb=True, is_board=True, name="CH340", label="/dev/ttyUSB1 — CH340",
    )
    monkeypatch.setattr(pyserial, "Serial", FakePySerial)
    monkeypatch.setattr(tmod, "find_fallback_port", lambda missing: fallback)
    monkeypatch.setattr(tmod.time, "sleep", lambda s: None)  # без паузы на ресет платы

    transport = tmod.SerialTransport(Config(port="/dev/ttyUSB0"))
    transport.connect()
    assert opened == ["/dev/ttyUSB1"]


def test_serial_no_fallback_reraises(monkeypatch):
    import serial as pyserial

    from adalight.device import DeviceError
    from adalight.plugins.builtin import transports as tmod

    def missing(*args, **kwargs):
        raise pyserial.SerialException("could not open port: FileNotFoundError")

    monkeypatch.setattr(pyserial, "Serial", missing)
    monkeypatch.setattr(tmod, "find_fallback_port", lambda missing_port: None)
    transport = tmod.SerialTransport(Config(port="/dev/ttyUSB0"))
    try:
        transport.connect()
        raise AssertionError("ожидали DeviceError")
    except DeviceError as e:
        assert "ttyUSB0" in str(e)
