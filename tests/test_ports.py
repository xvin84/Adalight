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
