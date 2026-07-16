"""Конфигурация приложения: dataclass + сохранение/загрузка в JSON."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

COLOR_ORDERS = ("RGB", "GRB", "BGR", "RBG", "GBR", "BRG")
START_CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")
DIRECTIONS = ("cw", "ccw")
BACKENDS = ("auto", "dxcam", "mss", "wfrecorder", "grim")

APP_NAME = "adalight"


def default_config_path() -> Path:
    """Путь к config.json в стандартном каталоге настроек текущей ОС."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME / "config.json"


@dataclass
class Config:
    # Железо
    port: str = "COM3" if sys.platform == "win32" else "/dev/ttyUSB0"
    baud: int = 115200
    color_order: str = "RGB"  # порядок каналов, ожидаемый лентой/прошивкой

    # Монитор ("" = первый/основной)
    output: str = ""

    # Светодиоды (количество по краям)
    leds_top: int = 15
    leds_right: int = 9
    leds_bottom: int = 15
    leds_left: int = 9

    # Ориентация ленты
    start_corner: str = "bottom-left"
    direction: str = "cw"  # cw | ccw
    flip_x: bool = False
    flip_y: bool = False

    # Захват и производительность
    backend: str = "auto"
    target_fps: int = 30
    grim_scale: float = 0.03

    # Обработка картинки
    band_size: float = 0.16   # толщина краевой полосы захвата (доля)
    window_size: float = 0.07 # ширина окна одного диода (доля)
    smooth: float = 0.3       # 0..1, больше = инертнее

    # Цветокоррекция
    gamma: float = 2.2
    brightness: float = 1.0
    saturation: float = 1.15

    @property
    def total_leds(self) -> int:
        return self.leds_top + self.leds_right + self.leds_bottom + self.leds_left

    def validate(self) -> None:
        if sorted(self.color_order) != sorted("RGB"):
            raise ValueError(f"Неверный порядок каналов: {self.color_order!r}")
        if self.start_corner not in START_CORNERS:
            raise ValueError(f"Неверный стартовый угол: {self.start_corner!r}")
        if self.direction not in DIRECTIONS:
            raise ValueError(f"Неверное направление: {self.direction!r}")
        if self.backend not in BACKENDS:
            raise ValueError(f"Неверный бэкенд захвата: {self.backend!r}")
        if min(self.leds_top, self.leds_right, self.leds_bottom, self.leds_left) < 0:
            raise ValueError("Количество диодов не может быть отрицательным")
        if self.total_leds == 0:
            raise ValueError("Суммарное количество диодов должно быть больше нуля")
        if self.baud <= 0:
            raise ValueError("Неверная скорость порта")
        if not 1 <= self.target_fps <= 240:
            raise ValueError("target_fps должен быть в диапазоне 1..240")
        if not 0.0 <= self.smooth < 1.0:
            raise ValueError("smooth должен быть в диапазоне [0, 1)")
        if not 0.0 < self.band_size <= 0.5 or not 0.0 < self.window_size <= 0.5:
            raise ValueError("band_size/window_size должны быть в диапазоне (0, 0.5]")
        if self.gamma <= 0 or self.brightness < 0 or self.saturation < 0:
            raise ValueError("Неверные параметры цветокоррекции")

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        """Загрузка конфига; неизвестные ключи игнорируются, отсутствующие берут дефолт."""
        p = path or default_config_path()
        if not p.is_file():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path | None = None) -> Path:
        p = path or default_config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        return p
