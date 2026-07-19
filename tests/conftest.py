"""Общие фикстуры тестов.

Эффекты лампы теперь регистрирует встроенный мод «effects_lamp» при включении.
В рантайме он включён по умолчанию (base=True). Чтобы тесты, дергающие
render_lamp напрямую, видели эффекты — регистрируем их перед каждым тестом
(как будто мод включён).
"""

import pytest


@pytest.fixture(autouse=True)
def _builtin_effects():
    from adalight.capture import register_builtin_capture_sources
    from adalight.effects import register_lamp_effect, register_music_effect
    from adalight.plugins.builtin import effects_lamp, effects_music

    for effect_id, label, render, flags in effects_lamp.LAMP_EFFECTS:
        register_lamp_effect(effect_id, label, render, source="effects_lamp", **flags)
    for effect_id, label, wants_color in effects_music.MUSIC_EFFECTS:
        register_music_effect(
            effect_id, label,
            lambda n, e=effect_id: effects_music.MusicRenderer(e, n),
            wants_color=wants_color, source="effects_music",
        )
    register_builtin_capture_sources(source="capture")
    yield
