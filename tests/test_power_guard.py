"""Мод «Защита питания»: расчёт тока, коэффициент приглушения, регулятор."""

import numpy as np
import pytest

from adalight import events, pipeline
from adalight.plugins.base import PluginAPI, schema_defaults
from adalight.plugins.builtin.power_guard import (
    DEFAULT_SETTINGS,
    PowerGuardPlugin,
    limit_ma,
    strip_current_ma,
    target_gain,
)
from adalight.plugins.manager import PluginManager

SETTINGS = dict(DEFAULT_SETTINGS)


def white(n: int = 10) -> np.ndarray:
    return np.full((n, 3), 255, dtype=np.uint8)


@pytest.fixture(autouse=True)
def _clean_filters():
    yield
    for spec in pipeline.frame_filters():
        pipeline.unregister_source(spec.source)


def test_schema_defaults_match_settings():
    """Форма настроек и значения по умолчанию мода не должны расходиться."""
    defaults = schema_defaults(PowerGuardPlugin.settings_schema)
    assert defaults == {k: v for k, v in DEFAULT_SETTINGS.items() if k != "enabled"}


def test_white_led_draws_60_ma():
    """Паспорт WS2812B: 20 мА на канал — белый диод берёт 60 мА (плюс покой)."""
    assert strip_current_ma(white(1), SETTINGS) == pytest.approx(61.0)


def test_current_is_linear_in_byte_value():
    """Средний ток пропорционален значению байта: половина яркости — половина тока."""
    half = np.full((10, 3), 128, dtype=np.uint8)
    lit = strip_current_ma(half, SETTINGS) - 10 * SETTINGS["idle_ma"]
    assert lit == pytest.approx(600.0 * 128 / 255, rel=1e-6)


def test_black_frame_still_draws_idle_current():
    """Чёрный кадр не бесплатен: чипы едят ток покоя, его не убрать затемнением."""
    assert strip_current_ma(np.zeros((60, 3), np.uint8), SETTINGS) == pytest.approx(60.0)


def test_limit_subtracts_headroom_and_board():
    assert limit_ma(SETTINGS) == pytest.approx(500 * 0.9 - 30)


def test_target_gain_fits_the_limit():
    """Приглушённый кадр обязан укладываться в лимит — это весь смысл мода."""
    frame = white(10)
    gain = target_gain(frame, SETTINGS)
    assert gain < 1.0
    lit = strip_current_ma(frame, SETTINGS) - 10 * SETTINGS["idle_ma"]
    assert lit * gain + 10 * SETTINGS["idle_ma"] == pytest.approx(limit_ma(SETTINGS))


def test_dark_frame_is_not_touched():
    dark = np.full((10, 3), 10, dtype=np.uint8)
    assert target_gain(dark, SETTINGS) == 1.0


def test_gain_never_goes_below_minimum():
    """Ниже минимальной яркости мод не опускает даже ценой превышения лимита."""
    settings = {**SETTINGS, "budget_ma": 100, "min_brightness": 0.2}
    assert target_gain(white(300), settings) == pytest.approx(0.2)


def test_budget_smaller_than_idle_gives_minimum():
    """Лимита не хватает даже на покой — гасим до минимума, но не в ноль."""
    settings = {**SETTINGS, "budget_ma": 40, "board_ma": 30, "min_brightness": 0.1}
    assert target_gain(white(60), settings) == pytest.approx(0.1)


# ── регулятор: срабатывание мгновенное, возврат плавный ────────────────────


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


@pytest.fixture
def plugin(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr("adalight.plugins.builtin.power_guard.time.monotonic", clock)
    mod = PowerGuardPlugin()
    mod.start(PluginAPI(flash=lambda *a: None, notify=lambda *a: None), {})
    mod.clock = clock
    return mod


def test_filter_dims_bright_frame_at_once(plugin):
    """Срабатывание по умолчанию мгновенное: лимит не превышается ни на кадр."""
    out = plugin.filter_frame(white(10))
    assert out is not None
    assert strip_current_ma(out, SETTINGS) <= limit_ma(SETTINGS) + 1e-6


def test_filter_leaves_safe_frame_alone(plugin):
    """Кадр в бюджете не трогаем вовсе — None экономит копию массива."""
    assert plugin.filter_frame(np.full((10, 3), 20, dtype=np.uint8)) is None


def test_brightness_returns_gradually(plugin):
    """После яркой сцены яркость возвращается плавно, а не скачком."""
    plugin.filter_frame(white(10))
    safe = np.full((10, 3), 20, dtype=np.uint8)

    plugin.clock.advance(0.1)
    plugin.filter_frame(safe)
    partial = plugin._gain
    assert 0.6 < partial < 1.0  # тронулся вверх, но далеко не восстановился

    for _ in range(100):  # 10 секунд при времени возврата 1.5 с
        plugin.clock.advance(0.1)
        plugin.filter_frame(safe)
    assert plugin._gain == pytest.approx(1.0, abs=1e-3)


def test_pause_does_not_snap_brightness_back(plugin):
    """После долгой паузы (сон, стоп) шаг ограничен — яркость не прыгает разом."""
    plugin.filter_frame(white(10))
    dimmed = plugin._gain

    plugin.clock.advance(600.0)  # десять минут без кадров
    plugin.filter_frame(np.full((10, 3), 20, dtype=np.uint8))
    assert dimmed < plugin._gain < 1.0


def test_repeated_bright_frames_do_not_oscillate(plugin):
    """Оценка берётся с исходного кадра, поэтому регулятор не «дышит»."""
    gains = []
    for _ in range(10):
        plugin.clock.advance(0.05)
        plugin.filter_frame(white(10))
        gains.append(plugin._gain)
    assert max(gains) - min(gains) < 1e-6


def test_status_event_reports_limit_and_release(plugin):
    seen: list[dict] = []
    events.subscribe("power.status", seen.append)

    plugin.filter_frame(white(10))
    assert seen and seen[-1]["limited"] is True
    assert seen[-1]["gain"] < 1.0
    assert seen[-1]["current_ma"] <= limit_ma(SETTINGS) + 1.0

    for _ in range(100):
        plugin.clock.advance(0.1)
        plugin.filter_frame(np.full((10, 3), 5, dtype=np.uint8))
    assert seen[-1]["limited"] is False  # UI должен узнать и о снятии ограничения


def test_status_event_is_not_spammed_every_frame(plugin):
    """На 100 fps шина не должна тонуть в статусах — репорт троттлится."""
    seen: list[dict] = []
    events.subscribe("power.status", seen.append)
    for _ in range(20):
        plugin.clock.advance(0.01)
        plugin.filter_frame(white(10))
    assert len(seen) == 1


def test_attack_smoothing_softens_the_drop(monkeypatch):
    """Со включённой плавностью срабатывания падение растянуто по времени."""
    clock = FakeClock()
    monkeypatch.setattr("adalight.plugins.builtin.power_guard.time.monotonic", clock)
    mod = PowerGuardPlugin()
    mod.start(PluginAPI(flash=lambda *a: None, notify=lambda *a: None), {"attack_s": 1.0})
    clock.advance(0.05)
    mod.filter_frame(white(10))
    assert mod._gain > target_gain(white(10), SETTINGS)


# ── интеграция с менеджером модов ──────────────────────────────────────────


def test_manager_registers_and_removes_filter():
    manager = PluginManager(PluginAPI(flash=lambda *a: None, notify=lambda *a: None))
    manager.apply({"power_guard": {"enabled": True}})
    assert "power_guard" in [s.id for s in pipeline.frame_filters()]

    manager.apply({"power_guard": {"enabled": False}})
    assert "power_guard" not in [s.id for s in pipeline.frame_filters()]
    manager.stop_all()


def test_disabled_by_default():
    """Мод меняет картинку, поэтому включает его пользователь, а не мы за него."""
    manager = PluginManager(PluginAPI(flash=lambda *a: None, notify=lambda *a: None))
    manager.apply({})
    assert not pipeline.has_frame_filters()
    manager.stop_all()


def test_status_marks_when_gain_hits_the_floor(monkeypatch):
    """Упёрлись в минимальную яркость — лимит превышен, и UI обязан это знать."""
    clock = FakeClock()
    monkeypatch.setattr("adalight.plugins.builtin.power_guard.time.monotonic", clock)
    mod = PowerGuardPlugin()
    mod.start(PluginAPI(flash=lambda *a: None, notify=lambda *a: None),
              {"min_brightness": 0.5})
    seen: list[dict] = []
    events.subscribe("power.status", seen.append)

    out = mod.filter_frame(white(60))
    assert seen[-1]["floored"] is True
    assert strip_current_ma(out, SETTINGS) > limit_ma(SETTINGS)


def test_default_minimum_keeps_a_usb_strip_within_budget():
    """60 диодов от USB — дефолтный минимум не должен ломать саму защиту."""
    frame = white(60)
    gain = target_gain(frame, SETTINGS)
    lit = strip_current_ma(frame, SETTINGS) - 60 * SETTINGS["idle_ma"]
    assert lit * gain + 60 * SETTINGS["idle_ma"] <= limit_ma(SETTINGS) + 1e-6
