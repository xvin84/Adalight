from dataclasses import dataclass

import serial.tools.list_ports as list_ports

from adalight.device import list_serial_ports, scan_serial_ports


@dataclass
class FakePort:
    device: str
    description: str = ""
    vid: int | None = None
    pid: int | None = None
    product: str | None = None


def _fake_comports(monkeypatch, ports):
    monkeypatch.setattr(list_ports, "comports", lambda: list(ports))


def test_arduino_native_usb_uses_product_name(monkeypatch):
    _fake_comports(monkeypatch, [
        FakePort("COM5", "Arduino Uno", vid=0x2341, pid=0x0043, product="Arduino Uno"),
    ])
    (p,) = scan_serial_ports()
    assert p.is_board and p.is_usb
    assert p.name == "Arduino Uno"
    assert p.label == "COM5 — Arduino Uno"


def test_ch340_bridge_uses_chip_name(monkeypatch):
    # у моста строка продукта неинформативна — показываем чип, а не «USB2.0-Serial»
    _fake_comports(monkeypatch, [
        FakePort("/dev/ttyUSB0", "USB2.0-Serial", vid=0x1A86, pid=0x7523, product="USB2.0-Serial"),
    ])
    (p,) = scan_serial_ports()
    assert p.is_board and p.is_usb
    assert p.name == "CH340"
    assert p.label == "/dev/ttyUSB0 — CH340"


def test_esp32_native_usb_recognized(monkeypatch):
    _fake_comports(monkeypatch, [
        FakePort("/dev/ttyACM0", "", vid=0x303A, pid=0x1001, product="ESP32-S3"),
    ])
    (p,) = scan_serial_ports()
    assert p.is_board
    assert p.name == "ESP32-S3"


def test_motherboard_uart_has_no_usb(monkeypatch):
    _fake_comports(monkeypatch, [
        FakePort("/dev/ttyS0", "ttyS0", vid=None, pid=None),
    ])
    (p,) = scan_serial_ports()
    assert not p.is_usb
    assert not p.is_board
    assert p.name == ""
    assert p.label == "/dev/ttyS0 — ttyS0"


def test_unknown_usb_is_usb_but_not_board(monkeypatch):
    _fake_comports(monkeypatch, [
        FakePort("COM9", "Some USB serial", vid=0x1234, pid=0x5678),
    ])
    (p,) = scan_serial_ports()
    assert p.is_usb
    assert not p.is_board
    assert p.name == ""


def test_sorted_boards_then_usb_then_bare(monkeypatch):
    _fake_comports(monkeypatch, [
        FakePort("/dev/ttyS0", "ttyS0"),                                   # без USB
        FakePort("COM9", "Some USB serial", vid=0x1234, pid=0x5678),       # USB, не плата
        FakePort("COM5", "Arduino Uno", vid=0x2341, pid=0x0043, product="Arduino Uno"),  # плата
    ])
    order = [p.device for p in scan_serial_ports()]
    assert order == ["COM5", "COM9", "/dev/ttyS0"]


def test_list_serial_ports_tuple_compat(monkeypatch):
    _fake_comports(monkeypatch, [
        FakePort("COM5", "Arduino Uno", vid=0x2341, pid=0x0043, product="Arduino Uno"),
        FakePort("/dev/ttyS0", "ttyS0"),
    ])
    pairs = list_serial_ports()
    assert pairs[0] == ("COM5", "Arduino Uno")
    assert pairs[1] == ("/dev/ttyS0", "ttyS0")


# ── распознавание чипа по паре VID:PID и стабильные пути by-id ────────────


def test_ch9102_recognized_by_pid(monkeypatch):
    # тот же вендор 1a86, что и CH340, но другой чип — различаем по PID
    _fake_comports(monkeypatch, [
        FakePort("/dev/ttyACM0", "USB Single Serial", vid=0x1A86, pid=0x55D4),
    ])
    (p,) = scan_serial_ports()
    assert p.is_board
    assert p.name == "CH9102"


def test_cp2102_and_ft232_recognized_by_pid(monkeypatch):
    _fake_comports(monkeypatch, [
        FakePort("/dev/ttyUSB0", "", vid=0x10C4, pid=0xEA60),
        FakePort("/dev/ttyUSB1", "", vid=0x0403, pid=0x6001),
    ])
    names = {p.device: p.name for p in scan_serial_ports()}
    assert names == {"/dev/ttyUSB0": "CP2102", "/dev/ttyUSB1": "FT232"}


def test_stable_device_uses_by_id_path(monkeypatch):
    import adalight.device as device_mod

    by_id = "/dev/serial/by-id/usb-1a86_USB2.0-Serial-if00-port0"
    # by-id — механизм Linux; на других ОС его вовсе не трогают, поэтому
    # поддержку включаем явно, чтобы тест проверял логику на любом хосте
    monkeypatch.setattr(device_mod, "stable_paths_supported", lambda: True)
    monkeypatch.setattr(device_mod, "_stable_paths", lambda: {"/dev/ttyUSB0": by_id})
    _fake_comports(monkeypatch, [
        FakePort("/dev/ttyUSB0", "USB2.0-Serial", vid=0x1A86, pid=0x7523),
    ])
    (p,) = scan_serial_ports()
    assert p.stable_device == by_id
    assert p.device == "/dev/ttyUSB0"  # ярлык остаётся человеческим


def test_stable_device_falls_back_to_device(monkeypatch):
    import adalight.device as device_mod

    monkeypatch.setattr(device_mod, "stable_paths_supported", lambda: True)
    monkeypatch.setattr(device_mod, "_stable_paths", lambda: {})
    _fake_comports(monkeypatch, [
        FakePort("COM5", "Arduino Uno", vid=0x2341, pid=0x0043, product="Arduino Uno"),
    ])
    (p,) = scan_serial_ports()
    assert p.stable_device == p.device == "COM5"


def test_scan_never_calls_realpath_without_by_id(monkeypatch):
    """Регрессия: realpath на имени COM-порта открывает устройство через
    CreateFileW и может бросить OSError (ERROR_GEN_FAILURE и подобные не входят
    в белый список ntpath) — приложение падало до старта окна. Там, где
    стабильных путей нет (Windows), realpath не должен вызываться вовсе."""
    import adalight.device as device_mod

    def boom(path):
        raise OSError(22, "WinError 1117: устройство недоступно")

    monkeypatch.setattr(device_mod, "stable_paths_supported", lambda: False)
    monkeypatch.setattr(device_mod.os.path, "realpath", boom)
    _fake_comports(monkeypatch, [
        FakePort("COM3", "USB-SERIAL CH340", vid=0x1A86, pid=0x7523),
        FakePort("COM5", "Arduino Uno", vid=0x2341, pid=0x0043, product="Arduino Uno"),
    ])
    ports = scan_serial_ports()
    assert [p.device for p in ports] == ["COM3", "COM5"]
    assert all(p.stable_device == p.device for p in ports)


def test_same_device_survives_realpath_failure(monkeypatch):
    import adalight.device as device_mod
    from adalight.device import same_device

    def boom(path):
        raise OSError(22, "устройство недоступно")

    monkeypatch.setattr(device_mod, "stable_paths_supported", lambda: True)
    monkeypatch.setattr(device_mod.os.path, "realpath", boom)
    assert same_device("COM3", "COM3")       # равенство строк — без realpath
    assert not same_device("COM3", "COM5")   # ошибка realpath не роняет вызов


def test_same_device_matches_via_realpath(monkeypatch):
    import adalight.device as device_mod
    from adalight.device import same_device

    by_id = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
    monkeypatch.setattr(device_mod, "stable_paths_supported", lambda: True)
    monkeypatch.setattr(
        device_mod.os.path, "realpath",
        lambda p: "/dev/ttyUSB0" if p in (by_id, "/dev/ttyUSB0") else p,
    )
    assert same_device(by_id, "/dev/ttyUSB0")
    assert not same_device(by_id, "/dev/ttyUSB1")


def test_no_realpath_on_windows_paths(monkeypatch):
    """На не-Linux same_device сравнивает строки и не трогает устройство."""
    import adalight.device as device_mod

    calls = []
    monkeypatch.setattr(device_mod, "stable_paths_supported", lambda: False)
    monkeypatch.setattr(device_mod.os.path, "realpath", lambda p: calls.append(p) or p)
    assert device_mod.same_device("COM3", "COM3")
    assert not device_mod.same_device("COM3", "COM7")
    assert calls == []


def test_stable_paths_maps_realpath_to_link(tmp_path):
    import os

    from adalight.device import _stable_paths

    target = tmp_path / "ttyUSB7"
    target.write_text("")
    by_id_dir = tmp_path / "by-id"
    by_id_dir.mkdir()
    link = by_id_dir / "usb-1a86_USB2.0-Serial-if00-port0"
    link.symlink_to(target)
    mapping = _stable_paths(by_id_dir)
    assert mapping == {os.path.realpath(target): str(link)}


def test_stable_paths_missing_dir_is_empty(tmp_path):
    from adalight.device import _stable_paths

    assert _stable_paths(tmp_path / "нет-такого") == {}


# ── фолбэк при пропаже порта: единственная плата ──────────────────────────


def _board(device: str):
    from adalight.device import PortInfo

    return PortInfo(
        device=device, description="", vid=0x1A86, pid=0x7523,
        is_usb=True, is_board=True, name="CH340", label=f"{device} — CH340",
    )


def test_fallback_finds_single_board(monkeypatch):
    import adalight.device as device_mod
    from adalight.device import find_fallback_port

    monkeypatch.setattr(device_mod, "scan_serial_ports", lambda: [_board("/dev/ttyUSB1")])
    p = find_fallback_port("/dev/ttyUSB0")
    assert p is not None and p.device == "/dev/ttyUSB1"


def test_fallback_none_when_port_present(monkeypatch):
    import adalight.device as device_mod
    from adalight.device import find_fallback_port

    monkeypatch.setattr(device_mod, "scan_serial_ports", lambda: [_board("/dev/ttyUSB0")])
    assert find_fallback_port("/dev/ttyUSB0") is None  # порт на месте — не гадаем


def test_fallback_none_when_ambiguous(monkeypatch):
    import adalight.device as device_mod
    from adalight.device import find_fallback_port

    monkeypatch.setattr(
        device_mod, "scan_serial_ports",
        lambda: [_board("/dev/ttyUSB1"), _board("/dev/ttyUSB2")],
    )
    assert find_fallback_port("/dev/ttyUSB0") is None  # две платы — не угадываем
