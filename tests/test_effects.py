import numpy as np
import pytest

from adalight.config import parse_hex_color
from adalight.effects import MusicRenderer, hsv_strip, render_lamp


def lamp_cfg(**kw) -> dict:
    base = {
        "lamp_effect": "solid",
        "lamp_color": "#ff9329",
        "lamp_color2": "#2962ff",
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


def test_music_output_bounds():
    r = MusicRenderer("spectrum", "#ffffff", gain=5.0, n_leds=16)
    out = r.render(np.random.default_rng(0).normal(0, 1, 1024), 48000)
    assert out.shape == (16, 3)
    assert out.min() >= 0.0 and out.max() <= 255.0
