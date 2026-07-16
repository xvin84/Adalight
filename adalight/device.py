"""Устройство Adalight: протокол, цветокоррекция и отправка по serial."""

from __future__ import annotations

import time

import numpy as np
import serial

from .config import Config


class DeviceError(RuntimeError):
    pass


def build_header(total_leds: int) -> bytes:
    """Заголовок протокола Adalight: 'Ada' + count_hi + count_lo + checksum."""
    count = total_leds - 1
    hi, lo = (count >> 8) & 0xFF, count & 0xFF
    return bytes([0x41, 0x64, 0x61, hi, lo, hi ^ lo ^ 0x55])


def color_order_indices(order: str) -> tuple[int, int, int]:
    """Индексы RGB-каналов в порядке, ожидаемом лентой (например GRB -> (1, 0, 2))."""
    return tuple("RGB".index(c) for c in order.upper())  # type: ignore[return-value]


def build_gamma_lut(gamma: float, brightness: float) -> np.ndarray:
    """LUT 0..255 -> 0..255 c гаммой и яркостью: считается один раз, а не на каждый кадр."""
    x = np.arange(256, dtype=np.float64) / 255.0
    y = np.power(x, gamma) * brightness * 255.0
    return np.clip(y, 0.0, 255.0).astype(np.uint8)


class AdalightDevice:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.ser: serial.Serial | None = None
        self._header = build_header(cfg.total_leds)
        self._order = color_order_indices(cfg.color_order)
        self._lut = build_gamma_lut(cfg.gamma, cfg.brightness)

    def connect(self) -> None:
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
        self.ser = None

    def process(self, colors: np.ndarray) -> np.ndarray:
        """Цветокоррекция: насыщенность + гамма/яркость (через LUT). Вход и выход — RGB."""
        c = np.clip(colors, 0.0, 255.0) / 255.0
        if self.cfg.saturation != 1.0:
            gray = c.mean(axis=1, keepdims=True)
            c = np.clip(gray + (c - gray) * self.cfg.saturation, 0.0, 1.0)
        return self._lut[(c * 255.0).astype(np.uint8)]

    def send_raw(self, colors: np.ndarray) -> None:
        """Отправка RGB-массива (N, 3) как есть, с учётом порядка каналов ленты."""
        if self.ser is None:
            return
        data = np.ascontiguousarray(
            np.clip(colors, 0, 255).astype(np.uint8)[:, self._order]
        )
        try:
            self.ser.write(self._header + data.tobytes())
        except serial.SerialException as e:
            raise DeviceError(f"Ошибка записи в порт {self.cfg.port}: {e}") from e

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
