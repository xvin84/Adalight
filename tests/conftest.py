"""Общие фикстуры тестов.

Эффекты лампы теперь регистрирует встроенный мод «effects_lamp» при включении.
В рантайме он включён по умолчанию (base=True). Чтобы тесты, дергающие
render_lamp напрямую, видели эффекты — регистрируем их перед каждым тестом
(как будто мод включён).
"""

import pytest


@pytest.fixture(autouse=True)
def _builtin_lamp_effects():
    from adalight.effects import register_lamp_effect
    from adalight.plugins.builtin import effects_lamp

    for effect_id, label, render, flags in effects_lamp.LAMP_EFFECTS:
        register_lamp_effect(effect_id, label, render, source="effects_lamp", **flags)
    yield
