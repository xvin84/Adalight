import numpy as np
import pytest

from adalight.config import parse_hex_color
from adalight.effects import MusicRenderer, hsv_strip, render_lamp


def lamp_cfg(**kw) -> dict:
    base = {
        "lamp_effect": "solid",
        "lamp_color": "#ff9329",
        "lamp_gradient": [
            {"pos": 0.0, "color": "#ff9329"},
            {"pos": 1.0, "color": "#2962ff"},
        ],
        "lamp_speed": 0.5,
    }
    base.update(kw)
    return base


def test_parse_hex_color():
    assert parse_hex_color("#FF9329") == (255, 147, 41)
    assert parse_hex_color("2962ff") == (41, 98, 255)


@pytest.mark.parametrize("bad", ["", "#fff", "#ggghhh", "#12345", "red"])
def test_parse_hex_color_rejects(bad):
    with pytest.raises(ValueError):
        parse_hex_color(bad)


def test_solid():
    out = render_lamp(lamp_cfg(), 10, t=0.0)
    assert out.shape == (10, 3)
    assert np.all(out == [255, 147, 41])


def test_gradient_endpoints():
    out = render_lamp(lamp_cfg(lamp_effect="gradient"), 5, t=0.0)
    assert np.allclose(out[0], (255, 147, 41))
    assert np.allclose(out[-1], (41, 98, 255))


def test_gradient_multi_stop_positions():
    grad = [
        {"pos": 0.0, "color": "#000000"},
        {"pos": 0.5, "color": "#ff0000"},
        {"pos": 1.0, "color": "#000000"},
    ]
    out = render_lamp(lamp_cfg(lamp_effect="gradient", lamp_gradient=grad), 11, t=0.0)
    assert np.allclose(out[5], (255, 0, 0))   # середина — чистый красный
    assert np.allclose(out[0], (0, 0, 0))
    assert np.allclose(out[-1], (0, 0, 0))
    assert out[2, 0] > 0                      # между точками — интерполяция


def test_rainbow_static_is_frozen():
    a = render_lamp(lamp_cfg(lamp_effect="rainbow_static"), 20, t=0.0)
    b = render_lamp(lamp_cfg(lamp_effect="rainbow_static"), 20, t=10.0)
    assert np.array_equal(a, b)  # статичная радуга не двигается
    assert not np.allclose(a[0], a[10])  # но оттенки вдоль ленты разные


def test_rainbow_range_and_motion():
    a = render_lamp(lamp_cfg(lamp_effect="rainbow", lamp_speed=1.0), 30, t=0.0)
    b = render_lamp(lamp_cfg(lamp_effect="rainbow", lamp_speed=1.0), 30, t=1.0)
    assert a.shape == (30, 3)
    assert a.min() >= 0.0 and a.max() <= 255.0
    assert not np.allclose(a, b)  # радуга вращается


def test_breathing_varies_brightness():
    cfg = lamp_cfg(lamp_effect="breathing", lamp_speed=1.0)
    frames = [render_lamp(cfg, 4, t=t).max() for t in np.linspace(0, 2, 20)]
    assert max(frames) > min(frames) * 2  # дышит, а не горит ровно
    assert min(frames) > 0  # но не гаснет полностью


def test_hsv_strip_pure_hues():
    out = hsv_strip(np.array([0.0, 1 / 3, 2 / 3]))
    assert np.allclose(out[0], (255, 0, 0))
    assert np.allclose(out[1], (0, 255, 0))
    assert np.allclose(out[2], (0, 0, 255))


def fire_points():
    from adalight.config import Config
    from adalight.geometry import LedGeometry

    cfg = Config(leds_top=10, leds_right=4, leds_bottom=10, leds_left=4)
    return LedGeometry(cfg).points


def test_fire_bottom_hotter_than_top():
    points = fire_points()
    n = len(points)
    frames = [
        render_lamp(lamp_cfg(lamp_effect="fire"), n, t, points)
        for t in np.linspace(0.0, 3.0, 12)
    ]
    avg = np.mean(frames, axis=0)
    sides = [s for s, _, _ in points]
    bottom = avg[[i for i, s in enumerate(sides) if s == "bottom"], 0].mean()
    top = avg[[i for i, s in enumerate(sides) if s == "top"], 0].mean()
    assert bottom > top * 1.4  # очаг снизу заметно жарче
    for f in frames:
        assert f.min() >= 0.0 and f.max() <= 255.0


def test_fire_flickers():
    points = fire_points()
    n = len(points)
    a = render_lamp(lamp_cfg(lamp_effect="fire"), n, 0.0, points)
    b = render_lamp(lamp_cfg(lamp_effect="fire"), n, 1.0, points)
    assert not np.allclose(a, b)  # пламя живёт


def _fire_avg(points, **kw):
    n = len(points)
    return np.mean(
        [
            render_lamp(lamp_cfg(lamp_effect="fire", fire_sparks=0, **kw), n, t, points)
            for t in np.linspace(0.0, 3.0, 10)
        ],
        axis=0,
    )


def test_fire_height_reaches_top():
    points = fire_points()
    top = [i for i, (s, _, _) in enumerate(points) if s == "top"]
    tall = _fire_avg(points, fire_height=1.5)
    short = _fire_avg(points, fire_height=0.3)
    assert tall[top].mean() > short[top].mean() * 1.5  # высокое пламя достаёт до верха


def test_fire_intensity_scales_brightness():
    points = fire_points()
    bright = _fire_avg(points, fire_intensity=1.5)
    dim = _fire_avg(points, fire_intensity=0.2)
    assert bright.mean() > dim.mean() * 1.5


def test_fire_without_sparks_is_deterministic():
    points = fire_points()
    n = len(points)
    cfg = lamp_cfg(lamp_effect="fire", fire_sparks=0)
    assert np.array_equal(
        render_lamp(cfg, n, 0.7, points), render_lamp(cfg, n, 0.7, points)
    )


def test_fire_without_points_does_not_crash():
    out = render_lamp(lamp_cfg(lamp_effect="fire"), 8, 0.5)
    assert out.shape == (8, 3)


def test_comet_moves_with_tail():
    cfg = lamp_cfg(lamp_effect="comet", lamp_speed=1.0)
    a = render_lamp(cfg, 30, t=0.0)
    b = render_lamp(cfg, 30, t=0.5)
    assert not np.allclose(a, b)             # комета бежит
    bright = a.max(axis=1)
    assert bright.max() > 200                # голова яркая
    assert (bright < 20).sum() > 10          # большая часть ленты тёмная


def test_aurora_bounds_and_motion():
    cfg = lamp_cfg(lamp_effect="aurora", lamp_speed=0.5)
    a = render_lamp(cfg, 24, t=0.0)
    b = render_lamp(cfg, 24, t=2.0)
    assert a.min() >= 0.0 and a.max() <= 255.0
    assert not np.allclose(a, b)             # сияние переливается
    assert not np.allclose(a[0], a[12])      # оттенки вдоль ленты разные


def test_starry_twinkles_over_dark_sky():
    cfg = lamp_cfg(lamp_effect="starry", lamp_speed=1.0)
    frames = [render_lamp(cfg, 40, t) for t in np.linspace(0.0, 4.0, 16)]
    assert not np.allclose(frames[0], frames[8])  # звёзды мерцают
    avg = np.mean(frames, axis=0)
    assert np.median(avg.max(axis=1)) < 90        # фон в основном тёмный
    assert max(f.max() for f in frames) > 180     # но вспышки яркие


def make_tone(freq: float, samplerate: int = 48000, n: int = 1024) -> np.ndarray:
    t = np.arange(n) / samplerate
    return np.sin(2 * np.pi * freq * t)


def test_music_pulse_reacts_to_bass():
    r = MusicRenderer("pulse", "#ff2d95", gain=1.0, n_leds=8)
    bass_frames = [r.render(make_tone(60.0), 48000) for _ in range(5)]
    silence = r.render(np.zeros(1024), 48000)
    # после нескольких блоков баса лента ярче, чем на тишине (уровень спадает)
    assert bass_frames[-1].max() > 0
    for _ in range(30):
        silence = r.render(np.zeros(1024), 48000)
    assert silence.max() < bass_frames[-1].max()


def test_music_spectrum_bass_lights_strip_start():
    r = MusicRenderer("spectrum", "#ffffff", gain=1.0, n_leds=12)
    out = None
    for _ in range(5):
        out = r.render(make_tone(60.0), 48000)
    head = out[:3].max()   # начало ленты — низкие частоты
    tail = out[-3:].max()  # конец — высокие
    assert head > tail


def test_music_wave_travels_outward():
    r = MusicRenderer("wave", "#ffffff", gain=1.0, n_leds=21)
    for _ in range(3):
        r.render(make_tone(60.0), 48000)     # бас рождает волну в центре

    def dist_of_peak(out: np.ndarray) -> int:
        return abs(int(out.max(axis=1).argmax()) - 10)  # расстояние пика от центра

    for _ in range(3):
        a = r.render(np.zeros(1024), 48000)
    for _ in range(6):
        b = r.render(np.zeros(1024), 48000)
    assert a.max() > 200 and b.max() > 200   # волна жива
    assert dist_of_peak(b) > dist_of_peak(a)  # и убегает от центра к краям


def test_music_beat_flashes_on_kick():
    r = MusicRenderer("beat", "#ff0000", gain=1.0, n_leds=8)
    # долгий тихий фон: скользящая средняя привыкает, стартовая вспышка затухает
    for _ in range(50):
        r.render(make_tone(60.0, n=1024) * 0.05, 48000)
    quiet = r.render(make_tone(60.0, n=1024) * 0.05, 48000)
    assert quiet.max() < 60                                # фон почти тёмный
    kick = r.render(make_tone(60.0, n=1024) * 1.0, 48000)  # удар баса
    assert kick.max() > 200
    faded = kick
    for _ in range(12):
        faded = r.render(make_tone(60.0, n=1024) * 0.02, 48000)
    assert faded.max() < 60  # между ударами затухает


def test_music_output_bounds():
    r = MusicRenderer("spectrum", "#ffffff", gain=5.0, n_leds=16)
    out = r.render(np.random.default_rng(0).normal(0, 1, 1024), 48000)
    assert out.shape == (16, 3)
    assert out.min() >= 0.0 and out.max() <= 255.0
