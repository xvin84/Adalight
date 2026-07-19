"""Встроенный мод «Транспорты».

Штатные способы доставки цветов на ленту — serial (Adalight-протокол по USB) и
WLED (UDP по Wi-Fi) — это мод, идущий в комплекте. Транспорт получает уже
готовые RGB-байты (конвейер цвета отработал в ядре) и только доставляет их.
"""

from __future__ import annotations

import socket
import time

import numpy as np
import serial

from ...config import Config
from ...device import DeviceError, build_header, color_order_indices

# WLED realtime-протоколы (https://kno.wled.ge/interfaces/udp-realtime/)
WLED_DRGB = 2       # до 490 диодов одним пакетом
WLED_DNRGB = 4      # с оффсетом, для длинных лент
WLED_TIMEOUT_S = 255  # 255 = не возвращаться к встроенным эффектам, пока идут пакеты
_DNRGB_CHUNK = 489


class SerialTransport:
    """Adalight по serial: заголовок + порядок каналов ленты."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.ser: serial.Serial | None = None
        self._header = build_header(cfg.total_leds)
        self._order = color_order_indices(cfg.color_order)

    def connect(self) -> None:
        try:
            self.ser = serial.Serial(self.cfg.port, self.cfg.baud, timeout=1)
        except serial.SerialException as e:
            raise DeviceError(f"Не удалось открыть порт {self.cfg.port}: {e}") from e
        time.sleep(2.5)  # Arduino перезагружается при открытии порта
        self.ser.reset_input_buffer()

    def send_raw(self, data8: np.ndarray) -> None:
        if self.ser is None:
            return
        data = np.ascontiguousarray(data8[:, self._order])
        try:
            self.ser.write(self._header + data.tobytes())
        except serial.SerialException as e:
            raise DeviceError(f"Ошибка записи в порт {self.cfg.port}: {e}") from e

    def close(self) -> None:
        if self.ser is not None and self.ser.is_open:
            time.sleep(0.1)  # дать уйти кадру гашения перед закрытием
            self.ser.close()
        self.ser = None


class WledTransport:
    """WLED по Wi-Fi: UDP DRGB/DNRGB (порядок каналов WLED применяет сам)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._sock: socket.socket | None = None
        self._addr: tuple[str, int] | None = None

    def connect(self) -> None:
        try:
            host = socket.gethostbyname(self.cfg.wled_host.strip())
        except OSError as e:
            raise DeviceError(f"WLED-хост {self.cfg.wled_host!r} не найден: {e}") from e
        self._addr = (host, self.cfg.wled_port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send_raw(self, data: np.ndarray) -> None:
        if self._sock is None or self._addr is None:
            return
        payload = np.ascontiguousarray(data).tobytes()
        try:
            if len(data) <= 490:
                self._sock.sendto(bytes((WLED_DRGB, WLED_TIMEOUT_S)) + payload, self._addr)
            else:
                for start in range(0, len(data), _DNRGB_CHUNK):
                    chunk = payload[start * 3 : (start + _DNRGB_CHUNK) * 3]
                    header = bytes(
                        (WLED_DNRGB, WLED_TIMEOUT_S, (start >> 8) & 0xFF, start & 0xFF)
                    )
                    self._sock.sendto(header + chunk, self._addr)
        except OSError as e:
            raise DeviceError(f"Ошибка отправки на WLED {self.cfg.wled_host}: {e}") from e

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
        self._sock = None


TRANSPORTS = [
    ("serial", "Serial (Adalight)", SerialTransport, {"needs_serial": True}),
    ("wled", "WLED по Wi-Fi (beta)", WledTransport, {"needs_network": True}),
]


class TransportsMod:
    name = "transports"
    title = "Транспорты"
    description = (
        "Способы доставки цветов на ленту: serial (Adalight по USB) и WLED "
        "(по Wi-Fi). Встроенный мод — выключение оставит подсветку без связи "
        "с лентой."
    )
    base = True

    def register(self, api) -> None:
        for transport_id, label, factory, flags in TRANSPORTS:
            api.register_transport(transport_id, label, factory, **flags)


def create_plugin() -> TransportsMod:
    return TransportsMod()
