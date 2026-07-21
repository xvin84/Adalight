"""Устройство Adalight: конвейер цвета (ядро) + доставка через транспорт-мод.

Цветокоррекция (насыщенность/температура/баланс белого/гамма/яркость) —
в ядре. Сама доставка байт на ленту (serial, WLED) — транспорт из реестра
(мод «Транспорты»); AdalightDevice ему делегирует connect/send_raw/close.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .config import Config


class DeviceError(RuntimeError):
    pass


def _kelvin_raw(kelvin: float) -> np.ndarray:
    """Аппроксимация Таннера Хелланда: температура (K) -> сырые RGB-веса 0..1."""
    t = min(max(kelvin, 1000.0), 40000.0) / 100.0
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
    else:
        r = 329.698727446 * ((t - 60) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60) ** -0.0755148492)
    if t >= 66:
        b = 255.0
    elif t <= 19:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(t - 10) - 305.0447927307
    return np.clip([r, g, b], 0.0, 255.0) / 255.0


_KELVIN_NEUTRAL = _kelvin_raw(6500.0)


def kelvin_to_rgb(kelvin: float) -> np.ndarray:
    """Цветовая температура (K) -> RGB-множители (максимальный канал = 1).

    Кривая нормирована так, что 6500K — строго нейтральный (1, 1, 1).
    """
    rgb = _kelvin_raw(kelvin) / _KELVIN_NEUTRAL
    return rgb / rgb.max()


def build_header(total_leds: int) -> bytes:
    """Заголовок протокола Adalight: 'Ada' + count_hi + count_lo + checksum."""
    count = total_leds - 1
    hi, lo = (count >> 8) & 0xFF, count & 0xFF
    return bytes([0x41, 0x64, 0x61, hi, lo, hi ^ lo ^ 0x55])


def color_order_indices(order: str) -> tuple[int, int, int]:
    """Индексы RGB-каналов в порядке, ожидаемом лентой (например GRB -> (1, 0, 2))."""
    return tuple("RGB".index(c) for c in order.upper())  # type: ignore[return-value]


def build_gamma_lut(gamma: float, brightness: float, black_threshold: float = 0.0) -> np.ndarray:
    """LUT 0..255 -> 0..255 c гаммой, яркостью и отсечкой шума в тенях.

    Считается один раз, а не на каждый кадр. Входные значения ниже
    black_threshold (доля 0..1) гасятся в ноль — тёмный шум не подсвечивает ленту.
    """
    x = np.arange(256, dtype=np.float64) / 255.0
    y = np.power(x, gamma) * brightness * 255.0
    y[x < black_threshold] = 0.0
    return np.clip(y, 0.0, 255.0).astype(np.uint8)


class AdalightDevice:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._transport: object | None = None  # создаётся в connect() из реестра
        self._gamma = cfg.gamma
        self._brightness = cfg.brightness
        self._saturation = cfg.saturation
        self._black_threshold = cfg.black_threshold
        self._temp_rgb = kelvin_to_rgb(cfg.color_temp)
        self._wb = np.array([cfg.wb_r, cfg.wb_g, cfg.wb_b], dtype=np.float64)
        self._lut = build_gamma_lut(self._gamma, self._brightness, self._black_threshold)

    def set_tuning(
        self,
        gamma: float | None = None,
        brightness: float | None = None,
        saturation: float | None = None,
        color_temp: float | None = None,
        black_threshold: float | None = None,
        white_balance: tuple[float, float, float] | None = None,
    ) -> None:
        """Смена цветокоррекции на лету — без переоткрытия порта (и без ресета платы)."""
        rebuild = False
        if gamma is not None and gamma != self._gamma:
            self._gamma, rebuild = gamma, True
        if brightness is not None and brightness != self._brightness:
            self._brightness, rebuild = brightness, True
        if black_threshold is not None and black_threshold != self._black_threshold:
            self._black_threshold, rebuild = black_threshold, True
        if saturation is not None:
            self._saturation = saturation
        if color_temp is not None:
            self._temp_rgb = kelvin_to_rgb(color_temp)
        if white_balance is not None:
            self._wb = np.array(white_balance, dtype=np.float64)
        if rebuild:
            self._lut = build_gamma_lut(self._gamma, self._brightness, self._black_threshold)

    def connect(self) -> None:
        from .transports import make_transport

        self._transport = make_transport(self.cfg.transport, self.cfg)
        if self._transport is None:
            raise DeviceError(
                f"Транспорт {self.cfg.transport!r} недоступен — "
                "включите мод «Транспорты»"
            )
        self._transport.connect()

    def close(self) -> None:
        if self._transport is not None:
            try:
                self.clear()  # погасить ленту перед закрытием
            finally:
                self._transport.close()
            self._transport = None

    def process(self, colors: np.ndarray) -> np.ndarray:
        """Цветокоррекция: насыщенность + гамма/яркость (через LUT). Вход и выход — RGB."""
        c = np.clip(colors, 0.0, 255.0) / 255.0
        if self._saturation != 1.0:
            gray = c.mean(axis=1, keepdims=True)
            c = np.clip(gray + (c - gray) * self._saturation, 0.0, 1.0)
        c = np.clip(c * self._temp_rgb * self._wb, 0.0, 1.0)  # температура + баланс белого
        return self._lut[(c * 255.0).astype(np.uint8)]

    def send_raw(self, colors: np.ndarray) -> None:
        """Отдать готовые RGB (N, 3) транспорту (он оформит протокол и доставит)."""
        if self._transport is not None:
            self._transport.send_raw(np.clip(colors, 0, 255).astype(np.uint8))

    def send_processed(self, colors: np.ndarray) -> np.ndarray:
        """Применяет цветокоррекцию, отправляет и возвращает итоговые RGB-цвета."""
        out = self.process(colors)
        self.send_raw(out)
        return out

    def clear(self) -> None:
        self.send_raw(np.zeros((self.cfg.total_leds, 3), dtype=np.uint8))


# Производители плат и USB-serial мостов, по которым узнаём Arduino/ESP.
# CH340/CP210x/FTDI — универсальные мосты: стоят и на клонах Arduino/ESP,
# и на обычных переходниках, поэтому это «вероятно плата», а не гарантия.
# Полный список портов всегда доступен по галочке «Показать все порты».
_BOARD_VENDORS: dict[int, str] = {
    0x2341: "Arduino",
    0x2A03: "Arduino",           # arduino.org / Genuino
    0x303A: "ESP32 (Espressif)",  # ESP32-S2/S3/C3 с родным USB
    0x1A86: "CH340",             # QinHeng — клоны, NodeMCU, ESP-платы
    0x10C4: "CP210x",            # Silicon Labs — девкиты ESP32/ESP8266
    0x0403: "FTDI",              # переходник FT232 — Nano-клоны
    0x2E8A: "Raspberry Pi Pico",
    0x239A: "Adafruit",
    0x16C0: "Teensy",            # общий VID Teensyduino / старых плат
}
# У этих производителей USB «родной» — строка продукта обычно и есть имя платы
# («Arduino Uno»); у мостов (CH340/CP210x/FTDI) продукт неинформативен.
_NATIVE_USB_VENDORS = frozenset({0x2341, 0x2A03, 0x303A, 0x239A, 0x2E8A})


@dataclass(frozen=True)
class PortInfo:
    """Serial-порт с распознаванием платы по USB-дескриптору."""

    device: str        # "/dev/ttyUSB0" или "COM5" — то, что уходит в cfg.port
    description: str    # сырое описание из pyserial
    vid: int | None
    pid: int | None
    is_usb: bool        # есть USB vid → это USB-устройство, а не ttyS* материнки
    is_board: bool      # узнан как Arduino/ESP/USB-serial мост
    name: str           # человеческое имя платы/чипа ("Arduino Uno", "CH340"), "" если нет
    label: str          # готовая строка для показа: "COM5 — Arduino Uno"


def scan_serial_ports() -> list[PortInfo]:
    """Все serial-порты с распознаванием плат; узнанные и USB — первыми.

    Ничего не отправляет в порт и не открывает его — читает только USB-дескриптор
    (VID/PID/product), ровно как «Get Board Info» в Arduino IDE.
    """
    from serial.tools import list_ports

    ports: list[PortInfo] = []
    for p in list_ports.comports():
        vid, pid = p.vid, p.pid
        vendor = _BOARD_VENDORS.get(vid or -1, "")
        product = (p.product or "").strip()
        if vid in _NATIVE_USB_VENDORS and product:
            name = product
        else:
            name = vendor
        desc = p.description or ""
        if name:
            label = f"{p.device} — {name}"
        elif desc and desc != "n/a":
            label = f"{p.device} — {desc}"
        else:
            label = p.device
        ports.append(
            PortInfo(
                device=p.device,
                description=desc,
                vid=vid,
                pid=pid,
                is_usb=vid is not None,
                is_board=bool(vendor),
                name=name,
                label=label,
            )
        )
    # платы вперёд, затем прочие USB, затем безусб (ttyS*), внутри — по имени
    ports.sort(key=lambda pi: (not pi.is_board, not pi.is_usb, pi.device))
    return ports


def list_serial_ports() -> list[tuple[str, str]]:
    """Доступные serial-порты: (устройство, имя/описание). Для CLI и мастера."""
    return [(p.device, p.name or p.description) for p in scan_serial_ports()]
