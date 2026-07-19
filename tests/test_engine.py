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


def _inject_fake_serial(engine, fake_serial) -> None:
    """Подсунуть движку serial-транспорт с фейковым портом (вместо connect)."""
    from adalight.plugins.builtin.transports import SerialTransport

    transport = SerialTransport(engine.device.cfg)
    transport.ser = fake_serial
    engine.device._transport = transport


def run_engine_briefly(cfg, backend, frames=3) -> tuple[FakeSerial, list]:
    """Гоняет live-движок до получения `frames` кадров и корректно его глушит."""
    fake_serial = FakeSerial()
    emitted = []
    engine = Engine(cfg, on_colors=emitted.append, backend_factory=lambda _cfg: backend)
    engine.device.connect = lambda: _inject_fake_serial(engine, fake_serial)

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
    engine.device.connect = lambda: _inject_fake_serial(engine, fake_serial)

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
    engine.device.connect = lambda: _inject_fake_serial(engine, fake_serial)

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
    engine.device.connect = lambda: _inject_fake_serial(engine, fake_serial)

    t = threading.Thread(target=engine.run, args=("live",))
    t.start()
    deadline = time.time() + 5.0
    while len(fake_serial.frames) < 2 and time.time() < deadline:
        time.sleep(0.01)
    engine.identify(3)
    seen = len(fake_serial.frames)
    # пик конверта вспышки — на ~12% длительности, ждём достаточно кадров
    while len(fake_serial.frames) < seen + 40 and time.time() < deadline:
        time.sleep(0.01)
    engine.stop()
    t.join(timeout=5.0)

    # берём самый яркий кадр вспышки (конверт разгорается и затухает)
    frames = [
        np.frombuffer(f[6:], np.uint8).reshape(-1, 3) for f in fake_serial.frames[seen:-1]
    ]
    best = max(frames, key=lambda c: int(c[3].sum()))
    assert best[3].min() > 120                     # выбранный диод вспыхнул белым
    assert best[3].sum() > best[0].sum() * 3       # заметно ярче остальных
    assert best[0].max() < 50


def test_add_overlay_lights_target_area():
    cfg = make_cfg(target_fps=120)
    fake_serial = FakeSerial()
    engine = Engine(cfg, backend_factory=lambda _: FakeBackend(color=(0, 0, 0)))
    engine.device.connect = lambda: _inject_fake_serial(engine, fake_serial)

    t = threading.Thread(target=engine.run, args=("live",))
    t.start()
    deadline = time.time() + 5.0
    while len(fake_serial.frames) < 2 and time.time() < deadline:
        time.sleep(0.01)
    # статичное пятно в правом нижнем углу
    engine.add_overlay("#00ff00", x=1.0, y=1.0, radius=0.3, duration=1.0, style="blob")
    seen = len(fake_serial.frames)
    while len(fake_serial.frames) < seen + 40 and time.time() < deadline:
        time.sleep(0.01)
    engine.stop()
    t.join(timeout=5.0)

    frames = [
        np.frombuffer(f[6:], np.uint8).reshape(-1, 3) for f in fake_serial.frames[seen:-1]
    ]
    best = max(frames, key=lambda c: int(c[:, 1].sum()))
    points = engine.geom.points
    near = [i for i, (_, x, y) in enumerate(points) if np.hypot(x - 1, y - 1) < 0.2]
    far = [i for i, (_, x, y) in enumerate(points) if np.hypot(x - 1, y - 1) > 0.8]
    assert best[near, 1].mean() > 60                    # у угла — зелёная вспышка
    assert best[near, 1].mean() > best[far, 1].mean() * 3  # далёкие почти не тронуты


def test_ripple_overlay_travels_outward():
    """«Бульк»: волна должна доходить до дальних диодов позже, чем до ближних."""
    cfg = make_cfg(target_fps=120)
    fake_serial = FakeSerial()
    engine = Engine(cfg, backend_factory=lambda _: FakeBackend(color=(0, 0, 0)))
    engine.device.connect = lambda: _inject_fake_serial(engine, fake_serial)

    t = threading.Thread(target=engine.run, args=("live",))
    t.start()
    deadline = time.time() + 5.0
    while len(fake_serial.frames) < 2 and time.time() < deadline:
        time.sleep(0.01)

    engine.add_overlay("#00ff00", x=1.0, y=1.0, radius=0.3, duration=1.0, style="ripple")
    seen = len(fake_serial.frames)
    started = time.time()
    # копим кадры на всю длительность волны
    while time.time() < started + 1.1 and time.time() < deadline:
        time.sleep(0.01)
    engine.stop()
    t.join(timeout=5.0)

    series = np.array(
        [
            np.frombuffer(f[6:], np.uint8).reshape(-1, 3)[:, 1]
            for f in fake_serial.frames[seen:-1]
        ]
    )
    assert len(series) > 20
    points = engine.geom.points
    near = min(range(len(points)), key=lambda i: np.hypot(points[i][1] - 1, points[i][2] - 1))
    far = max(range(len(points)), key=lambda i: np.hypot(points[i][1] - 1, points[i][2] - 1))
    assert series[:, near].max() > 60          # капля зажгла точку
    assert series[:, far].max() > 30           # волна дошла до дальнего края
    # ближний диод достигает пика раньше дальнего — волна расходится
    assert int(series[:, near].argmax()) < int(series[:, far].argmax())


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


class _OneFrameThenStatic(FakeBackend):
    """Отдаёт кадр один раз, потом None — как DXGI на статичном экране."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._served = False

    def get_frame(self):
        if self._served:
            return None
        self._served = True
        return self._frame


def _run_live(engine, seconds):
    fake_serial = FakeSerial()
    engine.device.connect = lambda: _inject_fake_serial(engine, fake_serial)
    t = threading.Thread(target=engine.run, args=("live",))
    t.start()
    time.sleep(seconds)
    engine.stop()
    t.join(timeout=5.0)
    assert not t.is_alive()
    return fake_serial


def test_keepalive_resends_on_static_screen():
    """Сон выключен: на статичном экране (DXGI отдаёт None) keep-alive шлёт кадры."""
    cfg = make_cfg(target_fps=120, sleep_enabled=False)
    engine = Engine(cfg, backend_factory=lambda _c: _OneFrameThenStatic())
    engine.KEEPALIVE_S = 0.05  # часто — чтобы тест был быстрым
    serial = _run_live(engine, 0.4)
    # без keep-alive был бы 1 кадр; с ним (0.05 с) за 0.4 с — заметно больше
    assert len(serial.frames) >= 4, len(serial.frames)


def test_sleep_turns_off_strip_after_idle():
    """Сон включён: без изменений на экране лента гаснет через таймаут."""
    cfg = make_cfg(target_fps=120, sleep_enabled=True)
    engine = Engine(cfg, backend_factory=lambda _c: FakeBackend(color=(100, 150, 200)))
    engine._sleep_timeout_s = 0.15  # короткий таймаут для теста
    serial = _run_live(engine, 0.5)
    frames = [np.frombuffer(f[6:], np.uint8).reshape(-1, 3) for f in serial.frames]
    # среди отправленных (кроме последнего — гашение при close) есть чёрный кадр (сон)
    assert any(fr.max() == 0 for fr in frames[:-1]), "лента не погасла по сну"
    # и до сна был цветной кадр
    assert any(fr.max() > 0 for fr in frames), "лента вообще не горела"


def test_engine_emits_started_and_stopped():
    from adalight import events

    cfg = make_cfg()
    engine = Engine(cfg)
    engine.device.connect = lambda: _inject_fake_serial(engine, FakeSerial())

    seen = []
    events.subscribe("engine.started", lambda p: seen.append(("started", p.get("mode"))))
    events.subscribe("engine.stopped", lambda p: seen.append(("stopped", p.get("mode"))))
    engine.run("off")
    assert seen == [("started", "off"), ("stopped", "off")]


def test_engine_stopped_emitted_even_on_error():
    from adalight import events

    cfg = make_cfg()
    engine = Engine(cfg)

    def boom():
        raise RuntimeError("порт недоступен")

    engine.device.connect = boom
    seen = []
    events.subscribe("engine.stopped", lambda p: seen.append(p.get("mode")))
    with pytest.raises(RuntimeError):
        engine.run("off")
    assert seen == ["off"]  # stopped эмитится через finally даже при исключении


def test_engine_frame_event_carries_colors():
    from adalight import events

    cfg = make_cfg()
    engine = Engine(cfg)
    engine.device.connect = lambda: _inject_fake_serial(engine, FakeSerial())

    frames = []
    events.subscribe("engine.frame", lambda p: frames.append(p["colors"]))
    engine.run("off")  # режим off эмитит один (нулевой) кадр
    assert len(frames) == 1
    assert frames[0].shape == (cfg.total_leds, 3)
