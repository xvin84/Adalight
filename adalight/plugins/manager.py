"""Обнаружение, запуск и остановка плагинов. Ошибки плагинов изолируются."""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path

from ..config import default_config_path
from .base import PluginAPI

BUILTIN_MODULES = ("adalight.plugins.builtin.notifications",)


def plugins_dir() -> Path:
    return default_config_path().parent / "plugins"


@dataclass
class LoadedPlugin:
    plugin: object | None
    name: str
    title: str
    description: str
    error: str = ""
    running: bool = False
    settings: dict = field(default_factory=dict)
    builtin: bool = False
    version: str = ""
    schema: list | None = None
    path: Path | None = None


def _load_from_module(module, *, builtin: bool = False, path: Path | None = None) -> LoadedPlugin:
    plugin = module.create_plugin()
    return LoadedPlugin(
        plugin=plugin,
        name=plugin.name,
        title=getattr(plugin, "title", plugin.name),
        description=getattr(plugin, "description", ""),
        builtin=builtin,
        version=str(getattr(plugin, "version", "")),
        schema=getattr(plugin, "settings_schema", None),
        path=path,
    )


def discover() -> list[LoadedPlugin]:
    """Встроенные плагины + пользовательские из <конфиг>/plugins/*.py."""
    found: list[LoadedPlugin] = []
    for module_name in BUILTIN_MODULES:
        try:
            found.append(
                _load_from_module(importlib.import_module(module_name), builtin=True)
            )
        except Exception as e:  # noqa: BLE001 — плагин не должен ронять приложение
            found.append(
                LoadedPlugin(None, module_name.rsplit(".", 1)[-1],
                             module_name, "", error=str(e), builtin=True)
            )
    user_dir = plugins_dir()
    if user_dir.is_dir():
        for path in sorted(user_dir.glob("*.py")):
            try:
                spec = importlib.util.spec_from_file_location(
                    f"adalight_user_plugin_{path.stem}", path
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                found.append(_load_from_module(module, path=path))
            except Exception as e:  # noqa: BLE001
                found.append(
                    LoadedPlugin(None, path.stem, path.name, "", error=str(e), path=path)
                )
    return found


class PluginManager:
    def __init__(self, api: PluginAPI):
        self.api = api
        self.plugins: list[LoadedPlugin] = discover()

    def get(self, name: str) -> LoadedPlugin | None:
        return next((p for p in self.plugins if p.name == name), None)

    def apply(self, plugins_cfg: dict) -> None:
        """Привести плагины к конфигу: включённые запустить, выключенные остановить.

        Изменившиеся настройки включённого плагина приводят к его перезапуску.
        """
        for loaded in self.plugins:
            if loaded.plugin is None:
                continue
            cfg = dict(plugins_cfg.get(loaded.name, {}))
            enabled = bool(cfg.get("enabled", False))
            if loaded.running and (not enabled or cfg != loaded.settings):
                self._stop(loaded)
            if enabled and not loaded.running:
                self._start(loaded, cfg)

    def stop_all(self) -> None:
        for loaded in self.plugins:
            if loaded.running:
                self._stop(loaded)

    def _start(self, loaded: LoadedPlugin, settings: dict) -> None:
        try:
            loaded.plugin.start(self.api, settings)
            loaded.settings = settings
            loaded.running = True
            loaded.error = ""
        except Exception as e:  # noqa: BLE001
            loaded.error = str(e)

    def _stop(self, loaded: LoadedPlugin) -> None:
        try:
            loaded.plugin.stop()
        except Exception as e:  # noqa: BLE001
            loaded.error = str(e)
        loaded.running = False
