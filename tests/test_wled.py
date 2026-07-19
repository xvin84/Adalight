import numpy as np
import pytest

from adalight.config import Config
from adalight.device import DeviceError
from adalight.plugins.builtin.transports import WledTransport


class FakeSocket:
    def __init__(self):
        self.packets: list[tuple[bytes, tuple]] = []

    def sendto(self, data: bytes, addr: tuple):
        self.packets.append((data, addr))

    def close(self):
        pass


def make_wled_transport(n_top: int) -> tuple[WledTransport, FakeSocket]:
    cfg = Config(
        transport="wled", wled_host="192.168.1.42",
        leds_top=n_top, leds_right=0, leds_bottom=0, leds_left=0,
    )
    wt = WledTransport(cfg)
    sock = FakeSocket()
    wt._sock = sock
    wt._addr = ("192.168.1.42", 21324)
    return wt, sock


def test_drgb_packet_format():
    wt, sock = make_wled_transport(3)
    wt.send_raw(np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=np.uint8))
    assert len(sock.packets) == 1
    data, addr = sock.packets[0]
    assert addr == ("192.168.1.42", 21324)
    assert data[0] == 2      # DRGB
    assert data[1] == 255    # timeout
    assert data[2:] == bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])


def test_dnrgb_for_long_strips():
    wt, sock = make_wled_transport(600)
    wt.send_raw(np.zeros((600, 3), dtype=np.uint8))
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
    wt = WledTransport(cfg)
    sock = FakeSocket()
    wt._sock = sock
    wt._addr = ("1.2.3.4", 21324)
    wt.send_raw(np.array([[10, 20, 30]], dtype=np.uint8))
    assert sock.packets[0][0][2:] == bytes([10, 20, 30])


def test_wled_connect_requires_host():
    with pytest.raises(ValueError):
        Config(transport="wled", wled_host="").validate()


def test_wled_unknown_host_raises_device_error():
    cfg = Config(transport="wled", wled_host="no-such-host.invalid")
    wt = WledTransport(cfg)
    with pytest.raises(DeviceError):
        wt.connect()
