"""Система плагинов Adalight.

Плагин — python-модуль с функцией `create_plugin()`, возвращающей объект с
атрибутами `name`, `title`, `description` и методами `start(api, settings)` /
`stop()`. Встроенные плагины живут в `adalight.plugins.builtin`, свои можно
класть в `<каталог настроек>/plugins/*.py`.
"""

from .base import PluginAPI
from .manager import PluginManager

__all__ = ["PluginAPI", "PluginManager"]
