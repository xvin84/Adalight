"""Обнаружение, запуск и остановка плагинов. Ошибки плагинов изолируются."""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path

from ..config import default_config_path
from .base import PluginAPI

BUILTIN_MODULES = (
    "adalight.plugins.builtin.effects_lamp",
    "adalight.plugins.builtin.notifications",
)


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
    base: bool = False  # базовый мод (эффекты/захват/…): предупреждать при выключении


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
        base=bool(getattr(plugin, "base", False)),
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
                if not hasattr(module, "create_plugin"):
                    continue  # это локаль (create_locale) — её подберёт discover_locales
                found.append(_load_from_module(module, path=path))
            except Exception as e:  # noqa: BLE001
                found.append(
                    LoadedPlugin(None, path.stem, path.name, "", error=str(e), path=path)
                )
    return found


@dataclass
class LoadedLocale:
    code: str
    name: str
    translations: dict
    builtin: bool = False
    path: Path | None = None


def discover_locales() -> list[LoadedLocale]:
    """Языки-локали из <конфиг>/plugins/*.py с функцией create_locale()."""
    found: list[LoadedLocale] = []
    user_dir = plugins_dir()
    if not user_dir.is_dir():
        return found
    for path in sorted(user_dir.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(
                f"adalight_locale_{path.stem}", path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if not hasattr(module, "create_locale"):
                continue
            loc = module.create_locale()
            found.append(
                LoadedLocale(
                    code=str(loc.code),
                    name=str(getattr(loc, "name", loc.code)),
                    translations=dict(getattr(loc, "translations", {})),
                    path=path,
                )
            )
        except Exception:  # noqa: BLE001 — битая локаль не должна ронять запуск
            continue
    return found


class PluginManager:
    def __init__(self, api: PluginAPI):
        self.api = api
        self.plugins: list[LoadedPlugin] = discover()
        # возможности (эффекты и т.п.) регистрируются при ВКЛЮЧЕНИИ в apply(),
        # а не при загрузке — чтобы выключение мода реально убирало функционал

    def _register_extensions(self, loaded: LoadedPlugin) -> None:
        """Дать моду зарегистрировать возможности (эффекты и т.п.) при включении.

        Необязательный метод mod.register(api) вызывается с API, помеченным
        именем мода, — чтобы при выключении снять именно его регистрации.
        """
        hook = getattr(loaded.plugin, "register", None)
        if callable(hook):
            try:
                hook(self.api.bound(loaded.name))
            except Exception as e:  # noqa: BLE001 — ошибка регистрации не роняет запуск
                loaded.error = str(e)

    @staticmethod
    def _unregister_capabilities(loaded: LoadedPlugin) -> None:
        """Снять всё, что мод зарегистрировал (при выключении)."""
        from ..effects import unregister_source

        unregister_source(loaded.name)

    def get(self, name: str) -> LoadedPlugin | None:
        return next((p for p in self.plugins if p.name == name), None)

    def install_from_path(self, path: Path) -> LoadedPlugin | None:
        """Загрузить только что установленный плагин без перезапуска.

        Возвращает LoadedPlugin (в т.ч. с error) или None, если файл — не плагин
        (например, локаль с create_locale). Плагин с тем же именем заменяется.
        """
        try:
            spec = importlib.util.spec_from_file_location(
                f"adalight_user_plugin_{path.stem}_{id(path)}", path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:  # noqa: BLE001
            loaded = LoadedPlugin(None, path.stem, path.name, "", error=str(e), path=path)
            self._replace(loaded)
            return loaded
        if not hasattr(module, "create_plugin"):
            return None  # локаль или иной файл — не плагин
        try:
            loaded = _load_from_module(module, path=path)
        except Exception as e:  # noqa: BLE001
            loaded = LoadedPlugin(None, path.stem, path.name, "", error=str(e), path=path)
        self._replace(loaded)  # возможности зарегистрируются при включении (apply)
        return loaded

    def _replace(self, loaded: LoadedPlugin) -> None:
        existing = self.get(loaded.name)
        if existing is not None:
            if existing.running:
                self._deactivate(existing)
            self.plugins = [p for p in self.plugins if p is not existing]
        self.plugins.append(loaded)

    def apply(self, plugins_cfg: dict) -> None:
        """Привести моды к конфигу. Включение регистрирует возможности и запускает
        фоновую работу; выключение снимает регистрации и останавливает. Базовые
        моды (base=True) включены по умолчанию. Смена настроек — перезапуск."""
        for loaded in self.plugins:
            if loaded.plugin is None:
                continue
            cfg = dict(plugins_cfg.get(loaded.name, {}))
            enabled = bool(cfg.get("enabled", loaded.base))
            if loaded.running and not enabled:
                self._deactivate(loaded)
            elif loaded.running and enabled and cfg != loaded.settings:
                self._stop(loaded)
                self._start(loaded, cfg)  # только перезапуск, регистрации не трогаем
            elif enabled and not loaded.running:
                self._activate(loaded, cfg)

    def stop_all(self) -> None:
        for loaded in self.plugins:
            if loaded.running:
                self._deactivate(loaded)

    def _activate(self, loaded: LoadedPlugin, settings: dict) -> None:
        self._register_extensions(loaded)  # эффекты и т.п. — в реестры
        self._start(loaded, settings)      # фоновая работа (если есть); running там

    def _deactivate(self, loaded: LoadedPlugin) -> None:
        self._stop(loaded)
        self._unregister_capabilities(loaded)  # возможности уходят из реестров
        loaded.running = False

    def _start(self, loaded: LoadedPlugin, settings: dict) -> None:
        try:
            if hasattr(loaded.plugin, "start"):
                loaded.plugin.start(self.api, settings)
            loaded.settings = settings
            loaded.running = True
            loaded.error = ""
        except Exception as e:  # noqa: BLE001
            loaded.error = str(e)

    def _stop(self, loaded: LoadedPlugin) -> None:
        try:
            if hasattr(loaded.plugin, "stop"):
                loaded.plugin.stop()
        except Exception as e:  # noqa: BLE001
            loaded.error = str(e)
        loaded.running = False
