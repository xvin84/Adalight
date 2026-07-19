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
