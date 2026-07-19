"""Реестр транспортов: как цвета доезжают до ленты (serial, WLED, …).

Транспорт — провайдер (мод «Транспорты» или плагин), фабрика создаёт объект с
методами connect(), send_raw(colors_uint8), close(). Конвейер цвета (гамма/
яркость/температура) остаётся в ядре (device.py) — транспорт получает уже
готовые RGB-байты и только доставляет их.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .config import Config

TransportFactory = Callable[[Config], object]


@dataclass
class TransportSpec:
    id: str
    label: str
    factory: TransportFactory
    needs_serial: bool = False    # GUI: показывать порт/скорость/порядок каналов
    needs_network: bool = False   # GUI: показывать адрес/порт хоста
    source: str = ""              # имя мода (для снятия при выключении)


_TRANSPORTS: dict[str, TransportSpec] = {}


def register_transport(
    transport_id: str,
    label: str,
    factory: TransportFactory,
    *,
    needs_serial: bool = False,
    needs_network: bool = False,
    source: str = "",
) -> None:
    """Добавить транспорт в реестр (повторный id — перезапись)."""
    _TRANSPORTS[transport_id] = TransportSpec(
        transport_id, label, factory, needs_serial, needs_network, source
    )


def unregister_source(source: str) -> None:
    """Снять транспорты, зарегистрированные модом source (при его выключении)."""
    for transport_id in [i for i, s in _TRANSPORTS.items() if s.source == source]:
        del _TRANSPORTS[transport_id]


def transports() -> list[TransportSpec]:
    return list(_TRANSPORTS.values())


def transport(transport_id: str) -> TransportSpec | None:
    return _TRANSPORTS.get(transport_id)


def make_transport(transport_id: str, cfg: Config) -> object | None:
    """Создать транспорт из реестра (None — не зарегистрирован)."""
    spec = _TRANSPORTS.get(transport_id)
    return spec.factory(cfg) if spec is not None else None
