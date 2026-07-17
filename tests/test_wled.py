import numpy as np
import pytest

from adalight.config import Config
from adalight.device import AdalightDevice, DeviceError


class FakeSocket:
    def __init__(self):
        self.packets: list[tuple[bytes, tuple]] = []

    def sendto(self, data: bytes, addr: tuple):
        self.packets.append((data, addr))

    def close(self):
        pass


def make_wled_device(n_top: int) -> tuple[AdalightDevice, FakeSocket]:
    cfg = Config(
        transport="wled", wled_host="192.168.1.42",
        leds_top=n_top, leds_right=0, leds_bottom=0, leds_left=0,
    )
    dev = AdalightDevice(cfg)
    sock = FakeSocket()
    dev._sock = sock
    dev._wled_addr = ("192.168.1.42", 21324)
    return dev, sock


def test_drgb_packet_format():
    dev, sock = make_wled_device(3)
    dev.send_raw(np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]]))
    assert len(sock.packets) == 1
    data, addr = sock.packets[0]
    assert addr == ("192.168.1.42", 21324)
    assert data[0] == 2      # DRGB
    assert data[1] == 255    # timeout
    assert data[2:] == bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])


def test_dnrgb_for_long_strips():
    dev, sock = make_wled_device(600)
    dev.send_raw(np.zeros((600, 3)))
    assert len(sock.packets) == 2  # 489 + 111
    first, second = sock.packets[0][0], sock.packets[1][0]
    assert first[0] == 4 and second[0] == 4       # DNRGB
    assert (first[2], first[3]) == (0, 0)          # offset 0
    assert (second[2] << 8) | second[3] == 489     # offset второго чанка
    assert len(first) == 4 + 489 * 3
    assert len(second) == 4 + 111 * 3


def test_wled_ignores_color_order():
    # порядок каналов применяет сам WLED — data уходит как есть (RGB)
    cfg = Config(
        transport="wled", wled_host="1.2.3.4", color_order="GRB",
        leds_top=1, leds_right=0, leds_bottom=0, leds_left=0,
    )
    dev = AdalightDevice(cfg)
    sock = FakeSocket()
    dev._sock = sock
    dev._wled_addr = ("1.2.3.4", 21324)
    dev.send_raw(np.array([[10, 20, 30]]))
    assert sock.packets[0][0][2:] == bytes([10, 20, 30])


def test_wled_connect_requires_host():
    with pytest.raises(ValueError):
        Config(transport="wled", wled_host="").validate()


def test_wled_unknown_host_raises_device_error():
    cfg = Config(transport="wled", wled_host="no-such-host.invalid")
    dev = AdalightDevice(cfg)
    with pytest.raises(DeviceError):
        dev.connect()
