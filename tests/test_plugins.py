import json

import numpy as np
import pytest

from adalight.plugins import catalog
from adalight.plugins.base import PluginAPI
from adalight.plugins.builtin.notifications import (
    DEFAULT_SETTINGS,
    NotificationsPlugin,
    create_plugin,
)
from adalight.plugins.manager import PluginManager, discover


def make_api(flashes=None, notes=None) -> PluginAPI:
    return PluginAPI(
        flash=lambda *a: (flashes if flashes is not None else []).append(a),
        notify=lambda t, x: (notes if notes is not None else []).append((t, x)),
    )


def test_discover_finds_builtin_notifications():
    names = [p.name for p in discover()]
    assert "notifications" in names


def test_match_rule():
    from adalight.plugins.builtin.notifications import match_rule

    assert match_rule("Telegram Desktop", DEFAULT_SETTINGS) == "#4fc3f7"
    assert match_rule("Discord", DEFAULT_SETTINGS) == "#7c4dff"
    assert match_rule("discord ptb", {"discord_color": "#123456"}) == "#123456"
    assert match_rule("Mail", DEFAULT_SETTINGS) is None


def test_plugin_flash_uses_settings():
    flashes = []
    plugin = NotificationsPlugin()
    plugin._api = make_api(flashes)
    plugin._settings = {**DEFAULT_SETTINGS, "x": 0.1, "y": 0.2, "radius": 0.5}
    plugin._flash("#ff0000")
    assert flashes == [("#ff0000", 0.1, 0.2, 0.5, 1.6, "ripple")]


def test_plugin_flash_style_blob():
    flashes = []
    plugin = NotificationsPlugin()
    plugin._api = make_api(flashes)
    plugin._settings = {**DEFAULT_SETTINGS, "flash_style": "blob"}
    plugin._flash("#ff0000")
    assert flashes[0][5] == "blob"


def test_example_plugin_template_is_valid():
    """Шаблон из examples/ обязан соответствовать контракту плагина."""
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parent.parent
        / "examples" / "plugins" / "break_reminder.py"
    )
    spec = importlib.util.spec_from_file_location("example_break_reminder", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin = module.create_plugin()
    assert plugin.name == "break_reminder"
    assert plugin.title and plugin.description
    flashes, notes = [], []
    plugin.start(make_api(flashes, notes), {"interval_min": 0.001})
    import time

    deadline = time.time() + 3.0
    while not flashes and time.time() < deadline:
        time.sleep(0.02)
    plugin.stop()
    assert flashes, "шаблон должен вспыхнуть за интервал"
    assert flashes[0][0] == "#2ecc71"
    assert notes and notes[0][0] == "Перерыв!"


def test_create_plugin_interface():
    plugin = create_plugin()
    assert plugin.name == "notifications"
    assert plugin.title and plugin.description
    assert callable(plugin.start) and callable(plugin.stop)


def test_schema_defaults():
    from adalight.plugins import schema_defaults

    schema = [
        {"type": "note", "label": "просто текст"},
        {"key": "n", "type": "int", "default": 50, "min": 1, "max": 240},
        {"key": "c", "type": "color", "default": "#2ecc71"},
        {"key": "nodefault", "type": "text"},
    ]
    assert schema_defaults(schema) == {"n": 50, "c": "#2ecc71"}
    assert schema_defaults(None) == {}


def test_example_plugin_declares_schema():
    """Шаблон объявляет settings_schema — менеджер построит форму сам."""
    import importlib.util
    from pathlib import Path

    from adalight.plugins import schema_defaults
    from adalight.plugins.manager import _load_from_module

    path = (
        Path(__file__).resolve().parent.parent
        / "examples" / "plugins" / "break_reminder.py"
    )
    spec = importlib.util.spec_from_file_location("example_break_reminder2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loaded = _load_from_module(module, path=path)
    assert loaded.schema is not None
    assert loaded.path == path and not loaded.builtin
    assert schema_defaults(loaded.schema) == {"interval_min": 50, "color": "#2ecc71"}


class RecordingPlugin:
    name = "recorder"
    title = "Recorder"
    description = "test"

    def __init__(self):
        self.calls: list[str] = []
        self.settings = None

    def start(self, api, settings):
        self.calls.append("start")
        self.settings = settings

    def stop(self):
        self.calls.append("stop")


def make_manager(plugin) -> PluginManager:
    from adalight.plugins.manager import LoadedPlugin

    manager = PluginManager.__new__(PluginManager)
    manager.api = make_api()
    manager.plugins = [
        LoadedPlugin(plugin, plugin.name, plugin.title, plugin.description)
    ]
    return manager


def test_manager_start_stop_cycle():
    plugin = RecordingPlugin()
    manager = make_manager(plugin)

    manager.apply({"recorder": {"enabled": True, "k": 1}})
    assert plugin.calls == ["start"]
    manager.apply({"recorder": {"enabled": True, "k": 1}})  # без изменений — no-op
    assert plugin.calls == ["start"]
    manager.apply({"recorder": {"enabled": True, "k": 2}})  # настройки изменились
    assert plugin.calls == ["start", "stop", "start"]
    assert plugin.settings == {"enabled": True, "k": 2}
    manager.apply({"recorder": {"enabled": False}})
    assert plugin.calls == ["start", "stop", "start", "stop"]
    manager.stop_all()  # уже остановлен — без повторного stop
    assert plugin.calls == ["start", "stop", "start", "stop"]


class BrokenPlugin(RecordingPlugin):
    name = "broken"

    def start(self, api, settings):
        raise RuntimeError("бум")


def test_manager_isolates_broken_plugin():
    plugin = BrokenPlugin()
    manager = make_manager(plugin)
    manager.apply({"broken": {"enabled": True}})
    loaded = manager.get("broken")
    assert loaded.error == "бум"
    assert loaded.running is False


# ── цвет от иконки ────────────────────────────────────────────────────────


def test_icon_accent_color_boosts_saturation():
    from adalight.plugins.builtin.notifications import icon_accent_color

    # тускло-синеватая иконка -> сочный синий акцент
    pixels = np.tile(np.array([[60, 70, 110, 255]]), (100, 1))
    color = icon_accent_color(pixels)
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    assert b > r and b > g       # оттенок сохранён
    assert b >= 220              # яркость подтянута
    assert (b - min(r, g)) > 80  # насыщенность подтянута


def test_icon_accent_color_ignores_transparent():
    from adalight.plugins.builtin.notifications import icon_accent_color

    pixels = np.array([[255, 0, 0, 0]] * 50 + [[0, 255, 0, 255]] * 5)
    color = icon_accent_color(pixels)
    assert int(color[3:5], 16) > 200  # прозрачный красный не учтён, взят зелёный
    assert icon_accent_color(np.array([[255, 0, 0, 0]])) is None


# ── каталог ───────────────────────────────────────────────────────────────


def make_entry(**kw) -> catalog.CatalogEntry:
    base = dict(
        name="demo", title="Демо", description="тест", kind="official",
        url="https://example.invalid/demo.py",
    )
    base.update(kw)
    return catalog.CatalogEntry(**base)


def test_parse_index_roundtrip():
    data = {
        "plugins": [
            {"name": "a", "title": "A", "description": "d", "kind": "official",
             "url": "https://x/a.py", "author": "me", "version": "1.0"},
            {"name": "b", "title": "B", "description": "d", "kind": "community",
             "url": "https://x/b.py"},
        ]
    }
    entries = catalog.parse_index(data)
    assert [e.name for e in entries] == ["a", "b"]
    assert entries[0].author == "me"
    assert entries[1].kind == "community"


@pytest.mark.parametrize(
    "raw",
    [
        {"title": "без name", "description": "d", "kind": "official", "url": "u"},
        {"name": "x", "title": "t", "description": "d", "kind": "vip", "url": "u"},
    ],
)
def test_parse_index_rejects(raw):
    with pytest.raises(ValueError):
        catalog.parse_index({"plugins": [raw]})


def test_repo_index_matches_schema():
    """plugins-index.json в корне репозитория обязан быть валидным."""
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "plugins-index.json"
    entries = catalog.parse_index(json.loads(path.read_text(encoding="utf-8")))
    assert any(e.name == "break_reminder" and e.kind == "official" for e in entries)


def test_install_writes_plugin(tmp_path):
    entry = make_entry()
    payload = b"def create_plugin():\n    return None\n"
    target = catalog.install(entry, base=tmp_path, fetcher=lambda url: payload)
    assert target.read_bytes() == payload
    assert catalog.is_installed("demo", tmp_path)
    assert not catalog.is_installed("other", tmp_path)


def test_install_rejects_non_plugin(tmp_path):
    with pytest.raises(ValueError):
        catalog.install(make_entry(), base=tmp_path, fetcher=lambda url: b"print('hi')")
    assert not catalog.is_installed("demo", tmp_path)
