"""Событийная шина: pub/sub, изоляция ошибок, снятие подписок по source."""

from adalight.events import EventBus


def test_subscribe_and_emit_delivers_payload():
    bus = EventBus()
    seen = []
    bus.subscribe("x", lambda p: seen.append(p))
    bus.emit("x", a=1, b="two")
    assert seen == [{"a": 1, "b": "two"}]


def test_emit_without_subscribers_is_noop():
    bus = EventBus()
    bus.emit("nobody", value=1)  # не должно падать
    assert not bus.has_subscribers("nobody")


def test_unsubscribe_via_returned_callable():
    bus = EventBus()
    seen = []
    off = bus.subscribe("x", lambda p: seen.append(p))
    bus.emit("x")
    off()
    bus.emit("x")
    assert len(seen) == 1
    assert not bus.has_subscribers("x")


def test_unsubscribe_source_drops_only_that_mod():
    bus = EventBus()
    a, b = [], []
    bus.subscribe("x", lambda p: a.append(p), source="mod_a")
    bus.subscribe("x", lambda p: b.append(p), source="mod_b")
    bus.unsubscribe_source("mod_a")
    bus.emit("x")
    assert a == [] and len(b) == 1
    assert bus.has_subscribers("x")


def test_broken_handler_does_not_break_others_or_emitter():
    bus = EventBus()
    good = []

    def boom(_p):
        raise RuntimeError("нарочно")

    bus.subscribe("x", boom)
    bus.subscribe("x", lambda p: good.append(p))
    bus.emit("x", ok=True)  # эмитер не должен упасть
    assert good == [{"ok": True}]


def test_has_subscribers_reflects_state():
    bus = EventBus()
    assert not bus.has_subscribers("x")
    off = bus.subscribe("x", lambda p: None)
    assert bus.has_subscribers("x")
    off()
    assert not bus.has_subscribers("x")


def test_plugin_api_on_emit_and_source_unsubscribe():
    """PluginAPI.on помечает подписку source, менеджер снимает её при выключении."""
    from adalight.events import bus as default_bus
    from adalight.events import unsubscribe_source
    from adalight.plugins.base import PluginAPI

    default_bus().clear()
    api = PluginAPI(flash=lambda *a: None, notify=lambda *a: None).bound("mymod")
    seen = []
    api.on("ping", lambda p: seen.append(p))
    api.emit("ping", n=1)
    assert seen == [{"n": 1}]
    unsubscribe_source("mymod")  # как делает менеджер при выключении мода
    api.emit("ping", n=2)
    assert seen == [{"n": 1}]
    default_bus().clear()
