import pytest

from adalight.config import Config
from adalight.geometry import LedGeometry


def make_cfg(**kw) -> Config:
    base = dict(leds_top=4, leds_right=2, leds_bottom=4, leds_left=2)
    base.update(kw)
    return Config(**base)


def test_total_count():
    geom = LedGeometry(make_cfg())
    assert len(geom.points) == 12


def test_walk_order_bottom_left_cw():
    geom = LedGeometry(make_cfg(start_corner="bottom-left", direction="cw"))
    sides = [s for s, _, _ in geom.points]
    assert sides == ["left"] * 2 + ["top"] * 4 + ["right"] * 2 + ["bottom"] * 4


def test_cw_starts_upward_from_bottom_left():
    geom = LedGeometry(make_cfg(start_corner="bottom-left", direction="cw"))
    ys = [y for s, _, y in geom.points if s == "left"]
    # слева при движении по часовой y должен убывать (снизу вверх)
    assert ys == sorted(ys, reverse=True)


def test_flip_x_swaps_left_right():
    plain = LedGeometry(make_cfg())
    flipped = LedGeometry(make_cfg(flip_x=True))
    swap = {"left": "right", "right": "left", "top": "top", "bottom": "bottom"}
    assert [s for s, _, _ in flipped.points] == [swap[s] for s, _, _ in plain.points]


def test_slices_within_frame():
    geom = LedGeometry(make_cfg())
    w, h = 640, 360
    for y1, y2, x1, x2 in geom.calculate_slices(w, h):
        assert 0 <= y1 < y2 <= h
        assert 0 <= x1 < x2 <= w


def test_invalid_corner_rejected():
    with pytest.raises(ValueError):
        LedGeometry(make_cfg(start_corner="middle"))
