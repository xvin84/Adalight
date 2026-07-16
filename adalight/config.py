"""Конфигурация приложения: dataclass + сохранение/загрузка в JSON."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .schedule import parse_rules

COLOR_ORDERS = ("RGB", "GRB", "BGR", "RBG", "GBR", "BRG")
START_CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")
DIRECTIONS = ("cw", "ccw")
BACKENDS = ("auto", "bettercam", "dxcam", "mss", "wfrecorder", "grim")
MODES = ("capture", "lamp", "music")
LAMP_EFFECTS = ("solid", "gradient", "rainbow", "breathing")
MUSIC_EFFECTS = ("spectrum", "pulse")

APP_NAME = "adalight"


def parse_hex_color(value: str) -> tuple[int, int, int]:
    """'#RRGGBB' -> (r, g, b); бросает ValueError на мусор."""
    s = str(value).strip().lstrip("#")
    if len(s) != 6:
        raise ValueError(f"Неверный цвет: {value!r} (ожидается #RRGGBB)")
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError as e:
        raise ValueError(f"Неверный цвет: {value!r} (ожидается #RRGGBB)") from e


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

    # Расписание яркости: [{"start": "08:00", "end": "20:00", "brightness": 0.9}, ...]
    schedule_enabled: bool = False
    schedule: list = field(default_factory=list)

    # Адаптивная яркость по средней яркости изображения
    adaptive_enabled: bool = False
    adaptive_min: float = 0.3
    adaptive_max: float = 1.0
    adaptive_speed: float = 0.05  # доля пути до цели за кадр (0..1]

    # Конвейер цвета
    color_temp: int = 6500        # цветовая температура, K (6500 = нейтрально)
    black_threshold: float = 0.0  # отсечка шума в тенях, доля 0..0.5
    night_mode: bool = False      # теплее, темнее, плавнее

    # Режим работы
    mode: str = "capture"  # capture | lamp | music

    # Лампа
    lamp_effect: str = "solid"  # solid | gradient | rainbow | breathing
    lamp_color: str = "#ff9329"
    lamp_color2: str = "#2962ff"
    lamp_speed: float = 0.5  # 0..1

    # Цветомузыка
    music_effect: str = "spectrum"  # spectrum | pulse
    music_color: str = "#ff2d95"
    music_gain: float = 1.0  # 0.1..5

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
        if self.schedule_enabled:
            parse_rules(self.schedule)  # бросает ValueError с номером строки
        if not 0.0 <= self.adaptive_min <= self.adaptive_max <= 2.0:
            raise ValueError("Адаптивная яркость: нужно 0 <= мин <= макс <= 2")
        if not 0.0 < self.adaptive_speed <= 1.0:
            raise ValueError("Адаптивная яркость: скорость должна быть в диапазоне (0, 1]")
        if not 1000 <= self.color_temp <= 10000:
            raise ValueError("Цветовая температура должна быть в диапазоне 1000..10000 K")
        if not 0.0 <= self.black_threshold <= 0.5:
            raise ValueError("Порог теней должен быть в диапазоне 0..0.5")
        if self.mode not in MODES:
            raise ValueError(f"Неверный режим: {self.mode!r}")
        if self.lamp_effect not in LAMP_EFFECTS:
            raise ValueError(f"Неверный эффект лампы: {self.lamp_effect!r}")
        if self.music_effect not in MUSIC_EFFECTS:
            raise ValueError(f"Неверный эффект цветомузыки: {self.music_effect!r}")
        for name in ("lamp_color", "lamp_color2", "music_color"):
            parse_hex_color(getattr(self, name))  # бросает ValueError
        if not 0.0 <= self.lamp_speed <= 1.0:
            raise ValueError("Скорость эффекта лампы должна быть в диапазоне 0..1")
        if not 0.1 <= self.music_gain <= 5.0:
            raise ValueError("Чувствительность цветомузыки должна быть в диапазоне 0.1..5")

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
