"""Устройство Adalight: протокол, цветокоррекция и отправка по serial."""

from __future__ import annotations

import math
import socket
import time

import numpy as np
import serial

from .config import Config

# WLED realtime-протоколы (https://kno.wled.ge/interfaces/udp-realtime/)
WLED_DRGB = 2       # до 490 диодов одним пакетом
WLED_DNRGB = 4      # с оффсетом, для длинных лент
WLED_TIMEOUT_S = 255  # 255 = не возвращаться к встроенным эффектам, пока идут пакеты
_DNRGB_CHUNK = 489


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
        self.ser: serial.Serial | None = None
        self._sock: socket.socket | None = None
        self._wled_addr: tuple[str, int] | None = None
        self._header = build_header(cfg.total_leds)
        self._order = color_order_indices(cfg.color_order)
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
        if self.cfg.transport == "wled":
            try:
                host = socket.gethostbyname(self.cfg.wled_host.strip())
            except OSError as e:
                raise DeviceError(
                    f"WLED-хост {self.cfg.wled_host!r} не найден: {e}"
                ) from e
            self._wled_addr = (host, self.cfg.wled_port)
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            return
        try:
            self.ser = serial.Serial(self.cfg.port, self.cfg.baud, timeout=1)
        except serial.SerialException as e:
            raise DeviceError(f"Не удалось открыть порт {self.cfg.port}: {e}") from e
        time.sleep(2.5)  # Arduino перезагружается при открытии порта
        self.ser.reset_input_buffer()

    def close(self) -> None:
        if self.ser and self.ser.is_open:
            try:
                self.clear()
                time.sleep(0.1)
            finally:
                self.ser.close()
        if self._sock is not None:
            try:
                self.clear()
            finally:
                self._sock.close()
        self.ser = None
        self._sock = None

    def process(self, colors: np.ndarray) -> np.ndarray:
        """Цветокоррекция: насыщенность + гамма/яркость (через LUT). Вход и выход — RGB."""
        c = np.clip(colors, 0.0, 255.0) / 255.0
        if self._saturation != 1.0:
            gray = c.mean(axis=1, keepdims=True)
            c = np.clip(gray + (c - gray) * self._saturation, 0.0, 1.0)
        c = np.clip(c * self._temp_rgb * self._wb, 0.0, 1.0)  # температура + баланс белого
        return self._lut[(c * 255.0).astype(np.uint8)]

    def send_raw(self, colors: np.ndarray) -> None:
        """Отправка RGB-массива (N, 3) как есть.

        Serial: заголовок Adalight + порядок каналов ленты.
        WLED: UDP DRGB/DNRGB (порядок каналов WLED применяет сам)."""
        data8 = np.clip(colors, 0, 255).astype(np.uint8)
        if self.cfg.transport == "wled":
            self._send_wled(data8)
            return
        if self.ser is None:
            return
        data = np.ascontiguousarray(data8[:, self._order])
        try:
            self.ser.write(self._header + data.tobytes())
        except serial.SerialException as e:
            raise DeviceError(f"Ошибка записи в порт {self.cfg.port}: {e}") from e

    def _send_wled(self, data: np.ndarray) -> None:
        if self._sock is None or self._wled_addr is None:
            return
        payload = np.ascontiguousarray(data).tobytes()
        try:
            if len(data) <= 490:
                self._sock.sendto(
                    bytes((WLED_DRGB, WLED_TIMEOUT_S)) + payload, self._wled_addr
                )
            else:
                for start in range(0, len(data), _DNRGB_CHUNK):
                    chunk = payload[start * 3 : (start + _DNRGB_CHUNK) * 3]
                    header = bytes(
                        (WLED_DNRGB, WLED_TIMEOUT_S, (start >> 8) & 0xFF, start & 0xFF)
                    )
                    self._sock.sendto(header + chunk, self._wled_addr)
        except OSError as e:
            raise DeviceError(f"Ошибка отправки на WLED {self.cfg.wled_host}: {e}") from e

    def send_processed(self, colors: np.ndarray) -> np.ndarray:
        """Применяет цветокоррекцию, отправляет и возвращает итоговые RGB-цвета."""
        out = self.process(colors)
        self.send_raw(out)
        return out

    def clear(self) -> None:
        self.send_raw(np.zeros((self.cfg.total_leds, 3), dtype=np.uint8))


def list_serial_ports() -> list[tuple[str, str]]:
    """Доступные serial-порты: (устройство, описание)."""
    from serial.tools import list_ports

    return [(p.device, p.description or "") for p in list_ports.comports()]
