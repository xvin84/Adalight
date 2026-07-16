import numpy as np

from adalight.config import Config
from adalight.device import (
    AdalightDevice,
    build_gamma_lut,
    build_header,
    color_order_indices,
)


def test_header_magic_and_checksum():
    h = build_header(50)
    assert h[:3] == b"Ada"
    count = 49
    hi, lo = (count >> 8) & 0xFF, count & 0xFF
    assert h[3] == hi and h[4] == lo
    assert h[5] == hi ^ lo ^ 0x55


def test_header_large_count():
    h = build_header(300)
    assert (h[3] << 8) | h[4] == 299


def test_color_order_indices():
    assert color_order_indices("RGB") == (0, 1, 2)
    assert color_order_indices("GRB") == (1, 0, 2)
    assert color_order_indices("BGR") == (2, 1, 0)


def test_gamma_lut_identity():
    lut = build_gamma_lut(gamma=1.0, brightness=1.0)
    assert np.array_equal(lut, np.arange(256, dtype=np.uint8))


def test_gamma_lut_monotonic_and_bounded():
    lut = build_gamma_lut(gamma=2.2, brightness=1.0)
    assert lut[0] == 0 and lut[255] == 255
    assert np.all(np.diff(lut.astype(int)) >= 0)


def test_process_applies_gamma_via_lut():
    cfg = Config(gamma=2.0, brightness=1.0, saturation=1.0)
    dev = AdalightDevice(cfg)
    colors = np.full((cfg.total_leds, 3), 128.0)
    out = dev.process(colors)
    expected = round((128 / 255) ** 2.0 * 255)
    assert np.all(np.abs(out.astype(int) - expected) <= 1)


def test_process_saturation_keeps_gray():
    cfg = Config(gamma=1.0, brightness=1.0, saturation=2.0)
    dev = AdalightDevice(cfg)
    gray = np.full((cfg.total_leds, 3), 100.0)
    out = dev.process(gray)
    assert np.all(out == out[0, 0])  # серый остаётся серым


class FakeSerial:
    is_open = True

    def __init__(self):
        self.written = b""

    def write(self, data):
        self.written += data


def test_send_raw_reorders_channels():
    cfg = Config(leds_top=1, leds_right=0, leds_bottom=0, leds_left=0, color_order="GRB")
    dev = AdalightDevice(cfg)
    fake = FakeSerial()
    dev.ser = fake
    dev.send_raw(np.array([[10, 20, 30]]))
    assert fake.written[:3] == b"Ada"
    assert list(fake.written[6:9]) == [20, 10, 30]  # G, R, B
