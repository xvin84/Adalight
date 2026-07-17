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
    assert flashes == [("#ff0000", 0.1, 0.2, 0.5, 1.6)]


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
