"""Мод «Компенсация цвета стены»: альбедо, множители каналов, фильтр кадра."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from adalight import events, pipeline
from adalight.plugins.base import PluginAPI, schema_defaults

# Мод живёт в examples/ (устанавливается из каталога), поэтому грузится как
# пользовательский плагин — файлом, а не импортом пакета.
_PATH = Path(__file__).resolve().parent.parent / "examples" / "plugins" / "wall_tint.py"
_spec = importlib.util.spec_from_file_location("example_wall_tint", _PATH)
wall_tint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wall_tint)

DEFAULTS = wall_tint.DEFAULTS


def settings(**over) -> dict:
    return {**DEFAULTS, **over}


def frame(value: int = 128, n: int = 4) -> np.ndarray:
    return np.full((n, 3), value, dtype=np.uint8)


def make_api(logs: list | None = None) -> PluginAPI:
    sink = logs if logs is not None else []
    return PluginAPI(
        flash=lambda *a: None, notify=lambda *a: None, log=sink.append
    ).bound("wall_tint")


@pytest.fixture(autouse=True)
def _clean_registries():
    yield
    for spec in pipeline.frame_filters():
        pipeline.unregister_source(spec.source)
    events.unsubscribe_source("wall_tint")


def test_schema_defaults_match_settings():
    """Форма настроек и значения по умолчанию мода не должны расходиться."""
    defaults = schema_defaults(wall_tint.WallTintPlugin.settings_schema)
    assert defaults == {k: v for k, v in DEFAULTS.items() if k != "enabled"}


def test_create_plugin_interface():
    plugin = wall_tint.create_plugin()
    assert plugin.name == "wall_tint"
    assert plugin.title and plugin.description
    assert callable(plugin.register) and callable(plugin.start) and callable(plugin.stop)


def test_albedo_is_normalized_to_strongest_channel():
    albedo = wall_tint.wall_albedo("#ff8080")
    assert albedo[0] == pytest.approx(1.0)
    assert albedo[1] == albedo[2] < 1.0


def test_neutral_wall_needs_no_correction():
    """Белая и серая стена отражают каналы одинаково — множители единичные."""
    for color in ("#ffffff", "#808080", "#1a1a1a"):
        gains = wall_tint.channel_gains(settings(wall_color=color))
        assert gains == pytest.approx([1.0, 1.0, 1.0])
        assert wall_tint.build_lut(gains) is None


def test_broken_color_is_treated_as_neutral():
    """Испорченное значение в конфиге не должно перекрашивать ленту."""
    assert wall_tint.wall_albedo("не цвет") == pytest.approx([1.0, 1.0, 1.0])


def test_red_wall_dims_the_red_channel():
    """Красная стена и так возвращает красный — его и приглушаем."""
    gains = wall_tint.channel_gains(settings(wall_color="#ff8080"))
    assert gains[0] < gains[1] == gains[2] == pytest.approx(1.0)


def test_full_compensation_neutralizes_the_reflection():
    """Смысл мода: свет ленты, умноженный на альбедо, снова нейтрален."""
    albedo = wall_tint.wall_albedo("#ff8080")
    gains = wall_tint.channel_gains(
        settings(wall_color="#ff8080", strength=100, min_gain=0.05)
    )
    reflected = gains * albedo
    assert reflected == pytest.approx([reflected[0]] * 3)


def test_zero_strength_is_transparent():
    gains = wall_tint.channel_gains(settings(wall_color="#ff0000", strength=0))
    assert gains == pytest.approx([1.0, 1.0, 1.0])


def test_strength_scales_between_none_and_full():
    """Половинная сила — между «не трогать» и полной коррекцией."""
    full = wall_tint.channel_gains(
        settings(wall_color="#ff8080", strength=100, min_gain=0.05)
    )
    half = wall_tint.channel_gains(
        settings(wall_color="#ff8080", strength=50, min_gain=0.05)
    )
    assert full[0] < half[0] < 1.0


def test_min_gain_limits_the_dimming():
    """Предел не даёт насыщенным обоям увести подсветку в монохром."""
    gains = wall_tint.channel_gains(
        settings(wall_color="#ff0000", strength=100, min_gain=0.4)
    )
    assert gains[0] == pytest.approx(0.4)


def test_bright_mode_restores_the_lost_lightness():
    """Режим «Яркость» возвращает светлоту общим множителем."""
    exact = wall_tint.channel_gains(settings(wall_color="#ff8080", strength=100))
    bright = wall_tint.channel_gains(
        settings(wall_color="#ff8080", strength=100, mode="bright")
    )
    assert float(wall_tint.LUMA @ bright) == pytest.approx(1.0)
    assert np.all(bright >= exact) and bright.sum() > exact.sum()


def test_bright_mode_respects_max_boost():
    """Зелёная стена требует усиления втрое — потолок держит его на пределе."""
    gains = wall_tint.channel_gains(
        settings(wall_color="#00ff00", strength=100, min_gain=0.05,
                 mode="bright", max_boost=2.0)
    )
    assert gains.max() == pytest.approx(2.0)
    assert float(wall_tint.LUMA @ gains) < 1.0  # до полной светлоты не дотянулись


def test_trim_applies_on_top_of_the_model():
    """Ручная доводка — поверх расчёта: адаптацию зрения моделью не взять."""
    plain = wall_tint.channel_gains(settings(wall_color="#ff8080"))
    trimmed = wall_tint.channel_gains(settings(wall_color="#ff8080", trim_b=0.5))
    assert trimmed[2] == pytest.approx(plain[2] * 0.5)
    assert trimmed[0] == pytest.approx(plain[0])


def test_lut_applies_gains_per_channel():
    plugin = wall_tint.create_plugin()
    plugin.start(make_api(), settings(wall_color="#ff8080", strength=100, min_gain=0.05))
    gains = wall_tint.channel_gains(
        settings(wall_color="#ff8080", strength=100, min_gain=0.05)
    )
    out = plugin.filter_frame(frame(128))
    assert out.dtype == np.uint8 and out.shape == (4, 3)
    assert np.all(out[:, 0] == round(128 * gains[0]))
    assert np.all(out[:, 1] == 128) and np.all(out[:, 2] == 128)


def test_neutral_settings_return_none():
    """Нечего менять — возвращаем None, кадр даже не копируется."""
    plugin = wall_tint.create_plugin()
    plugin.start(make_api(), settings(wall_color="#ffffff"))
    assert plugin.filter_frame(frame(200)) is None


def test_calibration_lights_pure_white():
    """По белому кадру и снимают цвет стены — коррекция на это время снята."""
    plugin = wall_tint.create_plugin()
    plugin.start(make_api(), settings(wall_color="#ff8080", calibrate=True))
    assert np.all(plugin.filter_frame(frame(30)) == 255)


def test_stop_disables_the_correction():
    plugin = wall_tint.create_plugin()
    plugin.start(make_api(), settings(wall_color="#ff8080"))
    assert plugin.filter_frame(frame(128)) is not None
    plugin.stop()
    assert plugin.filter_frame(frame(128)) is None


def test_filter_handles_float_frame_from_a_previous_filter():
    """Ядро приводит кадр к байтам только в конце цепочки — float допустим."""
    plugin = wall_tint.create_plugin()
    plugin.start(make_api(), settings(wall_color="#ff8080", strength=100, min_gain=0.05))
    out = plugin.filter_frame(np.full((4, 3), 300.0))  # и выше 255 тоже
    assert out.dtype == np.uint8 and np.all(out[:, 1] == 255)


def test_start_reports_gains_to_the_bus():
    seen: list[dict] = []
    events.subscribe("wall_tint.status", seen.append, source="test")
    logs: list[str] = []
    wall_tint.create_plugin().start(make_api(logs), settings(wall_color="#ff8080"))
    events.unsubscribe_source("test")
    assert seen and seen[0]["gains"][0] < 1.0 and seen[0]["calibrating"] is False
    assert logs and "#ff8080" in logs[0]


def test_filter_runs_before_power_guard():
    """Защита питания должна считать ток по кадру, который реально уйдёт в ленту."""
    from adalight.plugins.builtin.power_guard import PowerGuardPlugin

    wall_tint.create_plugin().register(make_api())
    PowerGuardPlugin().register(
        PluginAPI(flash=lambda *a: None, notify=lambda *a: None).bound("power_guard")
    )
    assert [spec.id for spec in pipeline.frame_filters()] == ["wall_tint", "power_guard"]


def test_registered_filter_works_through_the_pipeline():
    plugin = wall_tint.create_plugin()
    plugin.register(make_api())
    plugin.start(make_api(), settings(wall_color="#ff8080", strength=100, min_gain=0.05))
    out = pipeline.apply_frame_filters(frame(200))
    assert out.dtype == np.uint8 and out[0, 0] < 200 and out[0, 1] == 200


def test_manager_enables_and_disables_the_mod():
    """Полный цикл, как в GUI: включение регистрирует фильтр, выключение снимает."""
    from adalight.plugins.manager import PluginManager, _load_from_module

    manager = PluginManager.__new__(PluginManager)
    manager.api = make_api()
    manager.plugins = [_load_from_module(wall_tint, path=_PATH)]

    manager.apply({"wall_tint": {"enabled": True, "wall_color": "#ff8080"}})
    assert [spec.id for spec in pipeline.frame_filters()] == ["wall_tint"]
    assert not manager.plugins[0].error
    assert np.any(pipeline.apply_frame_filters(frame(200)) != 200)

    manager.apply({"wall_tint": {"enabled": False}})
    assert pipeline.frame_filters() == []
