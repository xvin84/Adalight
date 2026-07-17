import threading
import time

import numpy as np
import pytest

from adalight.config import Config
from adalight.engine import Engine, band_rects, localize_slice
from adalight.geometry import LedGeometry


def make_cfg(**kw) -> Config:
    base = dict(
        leds_top=4, leds_right=2, leds_bottom=4, leds_left=2,
        smooth=0.0, gamma=1.0, brightness=1.0, saturation=1.0,
    )
    base.update(kw)
    return Config(**base)


class FakeBackend:
    """Отдаёт однотонный кадр; умеет и полный кадр, и полосный режим."""

    supports_bands = False
    fallback_reason = None

    def __init__(self, color=(100, 150, 200), size=(120, 200)):
        self.height, self.width = size
        self._frame = np.full((self.height, self.width, 3), color, dtype=np.uint8)
        self.closed = False

    def get_frame(self):
        return self._frame

    def get_bands(self, rects):
        return {
            side: self._frame[t : t + h, x : x + w]
            for side, (x, t, w, h) in rects.items()
        }

    def close(self):
        self.closed = True


class BandFakeBackend(FakeBackend):
    supports_bands = True


class FakeSerial:
    is_open = True

    def __init__(self):
        self.frames: list[bytes] = []

    def write(self, data: bytes):
        self.frames.append(bytes(data))

    def close(self):
        self.is_open = False

    def reset_input_buffer(self):
        pass


def run_engine_briefly(cfg, backend, frames=3) -> tuple[FakeSerial, list]:
    """Гоняет live-движок до получения `frames` кадров и корректно его глушит."""
    fake_serial = FakeSerial()
    emitted = []
    engine = Engine(cfg, on_colors=emitted.append, backend_factory=lambda _cfg: backend)
    engine.device.connect = lambda: setattr(engine.device, "ser", fake_serial)

    t = threading.Thread(target=engine.run, args=("live",))
    t.start()
    deadline = time.time() + 5.0
    while len(fake_serial.frames) < frames and time.time() < deadline:
        time.sleep(0.01)
    engine.stop()
    t.join(timeout=5.0)
    assert not t.is_alive(), "движок не остановился"
    assert len(fake_serial.frames) >= frames, "движок не отправил ни одного кадра"
    fake_serial.frames.pop()  # последний кадр — гашение ленты при close()
    return fake_serial, emitted


@pytest.mark.parametrize("backend_cls", [FakeBackend, BandFakeBackend])
def test_live_uniform_frame_produces_uniform_colors(backend_cls):
    cfg = make_cfg(target_fps=120)
    backend = backend_cls(color=(100, 150, 200))
    serial, emitted = run_engine_briefly(cfg, backend)

    n = cfg.total_leds
    payload = serial.frames[-1]
    assert payload[:3] == b"Ada"
    colors = np.frombuffer(payload[6:], np.uint8).reshape(n, 3)
    # однотонный кадр -> все диоды одного цвета, близкого к исходному
    assert np.all(np.abs(colors.astype(int) - [100, 150, 200]) <= 2)
    assert emitted and emitted[-1].shape == (n, 3)
    assert backend.closed


def test_live_band_mode_equals_full_mode():
    cfg = make_cfg(target_fps=120)
    full_serial, _ = run_engine_briefly(cfg, FakeBackend())
    band_serial, _ = run_engine_briefly(cfg, BandFakeBackend())
    assert full_serial.frames[-1] == band_serial.frames[-1]


def test_adaptive_brightness_dims_dark_scene():
    cfg = make_cfg(
        target_fps=120,
        adaptive_enabled=True, adaptive_min=0.2, adaptive_max=1.0, adaptive_speed=1.0,
    )
    # тёмная сцена: lum ~ 40/255 -> коэффициент ~ 0.2 + 0.8*0.157 ~ 0.33
    serial, _ = run_engine_briefly(cfg, FakeBackend(color=(40, 40, 40)), frames=5)
    colors = np.frombuffer(serial.frames[-1][6:], np.uint8)
    assert colors.max() <= 20  # 40 * ~0.33 ~ 13, без адаптивности было бы 40


def test_set_tuning_brightness_applies_live():
    cfg = make_cfg(target_fps=120)
    fake_serial = FakeSerial()
    emitted = []
    engine = Engine(cfg, on_colors=emitted.append, backend_factory=lambda _: FakeBackend())
    engine.device.connect = lambda: setattr(engine.device, "ser", fake_serial)

    t = threading.Thread(target=engine.run, args=("live",))
    t.start()
    deadline = time.time() + 5.0
    while len(fake_serial.frames) < 2 and time.time() < deadline:
        time.sleep(0.01)
    engine.set_tuning(brightness=0.1)
    seen = len(fake_serial.frames)
    while len(fake_serial.frames) < seen + 3 and time.time() < deadline:
        time.sleep(0.01)
    engine.stop()
    t.join(timeout=5.0)

    before = np.frombuffer(fake_serial.frames[1][6:], np.uint8).max()
    after = np.frombuffer(fake_serial.frames[-2][6:], np.uint8).max()  # [-1] — гашение
    assert after < before / 3


def test_night_mode_dims_and_warms():
    day_serial, _ = run_engine_briefly(make_cfg(target_fps=120), FakeBackend(color=(200, 200, 200)))
    night_serial, _ = run_engine_briefly(
        make_cfg(target_fps=120, night_mode=True), FakeBackend(color=(200, 200, 200))
    )
    day = np.frombuffer(day_serial.frames[-1][6:], np.uint8).reshape(-1, 3)
    night = np.frombuffer(night_serial.frames[-1][6:], np.uint8).reshape(-1, 3)
    assert night.max() < day.max()          # темнее
    assert night[0, 2] < night[0, 0] * 0.7  # синий канал задавлен (теплее)


def test_lamp_mode_sends_solid_color():
    cfg = make_cfg(target_fps=120, mode="lamp", lamp_effect="solid", lamp_color="#ff0000")
    fake_serial = FakeSerial()
    emitted = []
    engine = Engine(cfg, on_colors=emitted.append)
    engine.device.connect = lambda: setattr(engine.device, "ser", fake_serial)

    t = threading.Thread(target=engine.run, args=("lamp",))
    t.start()
    deadline = time.time() + 5.0
    while len(fake_serial.frames) < 3 and time.time() < deadline:
        time.sleep(0.01)
    engine.stop()
    t.join(timeout=5.0)
    assert not t.is_alive()

    colors = np.frombuffer(fake_serial.frames[-2][6:], np.uint8).reshape(-1, 3)
    assert np.all(colors[:, 0] > 200)  # красный горит
    assert np.all(colors[:, 1] == 0) and np.all(colors[:, 2] == 0)


def test_identify_flashes_single_led():
    cfg = make_cfg(target_fps=120)
    fake_serial = FakeSerial()
    engine = Engine(cfg, backend_factory=lambda _: FakeBackend(color=(10, 10, 10)))
    engine.device.connect = lambda: setattr(engine.device, "ser", fake_serial)

    t = threading.Thread(target=engine.run, args=("live",))
    t.start()
    deadline = time.time() + 5.0
    while len(fake_serial.frames) < 2 and time.time() < deadline:
        time.sleep(0.01)
    engine.identify(3)
    seen = len(fake_serial.frames)
    while len(fake_serial.frames) < seen + 2 and time.time() < deadline:
        time.sleep(0.01)
    engine.stop()
    t.join(timeout=5.0)

    colors = np.frombuffer(fake_serial.frames[-2][6:], np.uint8).reshape(-1, 3)
    assert np.array_equal(colors[3], (255, 255, 255))  # выбранный диод — белый
    assert colors[0].max() < 50                        # остальные — тёмные


def test_band_rects_and_localize_roundtrip():
    cfg = make_cfg(band_size=0.2, window_size=0.1)
    geom = LedGeometry(cfg)
    w, h = 200, 120
    bw, bh = int(w * 0.2), int(h * 0.2)
    slices = geom.calculate_slices(w, h)
    sides = [s for s, _, _ in geom.points]
    rects = band_rects(w, h, 0.2, set(sides))

    frame = np.arange(w * h * 3, dtype=np.int64).reshape(h, w, 3)
    bands = {side: frame[t : t + hh, x : x + ww] for side, (x, t, ww, hh) in rects.items()}

    for i, slc in enumerate(slices):
        y1, y2, x1, x2 = slc
        ly1, ly2, lx1, lx2 = localize_slice(sides[i], slc, w, h, bw, bh)
        assert np.array_equal(frame[y1:y2, x1:x2], bands[sides[i]][ly1:ly2, lx1:lx2])
