"""Конфигурация приложения: dataclass + сохранение/загрузка в JSON."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .schedule import parse_rules

COLOR_ORDERS = ("RGB", "GRB", "BGR", "RBG", "GBR", "BRG")
START_CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")
DIRECTIONS = ("cw", "ccw")
BACKENDS = ("auto", "bettercam", "dxcam", "mss", "wfrecorder", "grim")
MODES = ("capture", "lamp", "music")
LAMP_EFFECTS = ("solid", "gradient", "rainbow", "rainbow_static", "breathing")
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
    # баланс белого: множители каналов поверх температуры (калибровка ленты)
    wb_r: float = 1.0
    wb_g: float = 1.0
    wb_b: float = 1.0

    # Режим работы
    mode: str = "capture"  # capture | lamp | music

    # Лампа
    lamp_effect: str = "solid"  # solid | gradient | rainbow | rainbow_static | breathing
    lamp_color: str = "#ff9329"
    lamp_speed: float = 0.5  # 0..1
    # градиент: произвольные точки «позиция вдоль ленты -> цвет»
    lamp_gradient: list = field(
        default_factory=lambda: [
            {"pos": 0.0, "color": "#ff9329"},
            {"pos": 1.0, "color": "#2962ff"},
        ]
    )

    # Цветомузыка
    music_effect: str = "spectrum"  # spectrum | pulse
    music_color: str = "#ff2d95"
    music_gain: float = 1.0  # 0.1..5

    # Внешний вид
    theme: str = "dark"          # dark | light | system
    preview_screen: bool = True  # показывать картинку экрана в предпросмотре
    preview_zones: bool = True   # показывать зоны сбора цвета

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
        for name in ("lamp_color", "music_color"):
            parse_hex_color(getattr(self, name))  # бросает ValueError
        if not 0.0 <= self.lamp_speed <= 1.0:
            raise ValueError("Скорость эффекта лампы должна быть в диапазоне 0..1")
        if len(self.lamp_gradient) < 2:
            raise ValueError("Градиенту нужно минимум две цветовые точки")
        for i, stop in enumerate(self.lamp_gradient, start=1):
            try:
                pos = float(stop["pos"])
                parse_hex_color(stop["color"])
            except (KeyError, TypeError, ValueError) as e:
                raise ValueError(f"Точка градиента {i}: {e}") from e
            if not 0.0 <= pos <= 1.0:
                raise ValueError(f"Точка градиента {i}: позиция должна быть 0..1")
        if not 0.1 <= self.music_gain <= 5.0:
            raise ValueError("Чувствительность цветомузыки должна быть в диапазоне 0.1..5")
        if self.theme not in ("dark", "light", "system"):
            raise ValueError(f"Неверная тема: {self.theme!r}")
        for name in ("wb_r", "wb_g", "wb_b"):
            if not 0.2 <= getattr(self, name) <= 1.5:
                raise ValueError("Баланс белого: множители должны быть в диапазоне 0.2..1.5")

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


# ── профили: именованные конфиги в <конфиг-каталог>/profiles/*.json ──────


def profiles_dir(base: Path | None = None) -> Path:
    return (base or default_config_path().parent) / "profiles"


def _profile_path(name: str, base: Path | None = None) -> Path:
    clean = re.sub(r'[\\/:*?"<>|]', "", name).strip()
    if not clean:
        raise ValueError(f"Недопустимое имя профиля: {name!r}")
    return profiles_dir(base) / f"{clean}.json"


def list_profiles(base: Path | None = None) -> list[str]:
    d = profiles_dir(base)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def save_profile(name: str, cfg: Config, base: Path | None = None) -> Path:
    return cfg.save(_profile_path(name, base))


def load_profile(name: str, base: Path | None = None) -> Config:
    p = _profile_path(name, base)
    if not p.is_file():
        raise ValueError(f"Профиль «{name}» не найден")
    return Config.load(p)


def delete_profile(name: str, base: Path | None = None) -> None:
    _profile_path(name, base).unlink(missing_ok=True)
