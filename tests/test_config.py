import json

import pytest

from adalight.config import (
    Config,
    delete_profile,
    list_profiles,
    load_profile,
    save_profile,
)


def test_roundtrip(tmp_path):
    cfg = Config(
        port="COM7",
        leds_top=20,
        color_order="GRB",
        smooth=0.5,
        schedule_enabled=True,
        schedule=[{"start": "08:00", "end": "20:00", "brightness": 0.9}],
        adaptive_enabled=True,
        adaptive_min=0.25,
    )
    p = cfg.save(tmp_path / "config.json")
    loaded = Config.load(p)
    assert loaded == cfg


def test_load_missing_file_returns_defaults(tmp_path):
    assert Config.load(tmp_path / "nope.json") == Config()


def test_load_ignores_unknown_keys(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"port": "COM9", "legacy_option": 42}), encoding="utf-8")
    cfg = Config.load(p)
    assert cfg.port == "COM9"


def test_validate_accepts_defaults():
    Config().validate()


@pytest.mark.parametrize(
    "kw",
    [
        {"color_order": "RGBW"},
        {"direction": "up"},
        {"start_corner": "center"},
        {"leds_top": 0, "leds_right": 0, "leds_bottom": 0, "leds_left": 0},
        {"leds_top": -1},
        {"smooth": 1.0},
        {"target_fps": 0},
        {"band_size": 0.0},
        {"backend": "opengl"},
        {"schedule_enabled": True, "schedule": [{"start": "8", "end": "9", "brightness": 1}]},
        {"adaptive_min": 0.9, "adaptive_max": 0.2},
        {"adaptive_speed": 0.0},
        {"mode": "disco"},
        {"lamp_effect": "strobe"},
        {"lamp_color": "красный"},
        {"music_effect": "waves"},
        {"music_gain": 0.0},
        {"color_temp": 500},
        {"black_threshold": 0.9},
        {"lamp_gradient": [{"pos": 0.0, "color": "#ff0000"}]},
        {"lamp_gradient": [{"pos": 0.0, "color": "#ff0000"}, {"pos": 2.0, "color": "#00ff00"}]},
        {"lamp_gradient": [{"pos": 0.0, "color": "мусор"}, {"pos": 1.0, "color": "#00ff00"}]},
        {"theme": "neon"},
        {"wb_r": 0.1},
        {"wb_b": 2.0},
    ],
)
def test_validate_rejects_bad_values(kw):
    with pytest.raises(ValueError):
        Config(**kw).validate()


def test_profiles_roundtrip(tmp_path):
    assert list_profiles(tmp_path) == []
    cfg = Config(brightness=0.42, mode="lamp")
    save_profile("Кино", cfg, tmp_path)
    save_profile("Игра", Config(), tmp_path)
    assert list_profiles(tmp_path) == ["Игра", "Кино"]
    assert load_profile("Кино", tmp_path) == cfg
    delete_profile("Кино", tmp_path)
    assert list_profiles(tmp_path) == ["Игра"]
    delete_profile("Кино", tmp_path)  # повторное удаление не падает


def test_profile_name_sanitized(tmp_path):
    save_profile('Ки/но: "тест"?', Config(), tmp_path)
    assert list_profiles(tmp_path) == ["Кино тест"]


def test_profile_bad_names(tmp_path):
    with pytest.raises(ValueError):
        save_profile("///", Config(), tmp_path)
    with pytest.raises(ValueError):
        load_profile("нет такого", tmp_path)
