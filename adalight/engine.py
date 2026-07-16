"""Движок подсветки: цикл захват -> усреднение зон -> сглаживание -> отправка.

Не зависит от Qt: CLI использует его напрямую, GUI — в отдельном потоке через
колбэки. Параметры изображения (гамма/яркость/насыщенность/сглаживание),
расписание и адаптивная яркость меняются на лету через set_tuning() —
без перезапуска и без ресета платы.
"""

from __future__ import annotations

import datetime
import threading
import time
from collections.abc import Callable
from typing import Literal

import numpy as np

from .capture import create_backend
from .config import Config
from .device import AdalightDevice
from .effects import MusicRenderer, render_lamp
from .geometry import LedGeometry, Slice
from .schedule import ScheduleRule, brightness_at, parse_rules

Mode = Literal["live", "lamp", "music", "chase", "sides", "off"]

# Ночной режим: теплее, темнее, плавнее
NIGHT_COLOR_TEMP = 3400
NIGHT_BRIGHTNESS_FACTOR = 0.6
NIGHT_MIN_SMOOTH = 0.7

SIDE_TEST_PALETTE = {
    "top": (255, 0, 0),      # красный
    "right": (0, 255, 0),    # зелёный
    "bottom": (0, 0, 255),   # синий
    "left": (255, 200, 0),   # жёлтый
}


def band_rects(
    width: int, height: int, band_size: float, sides: set[str]
) -> dict[str, tuple[int, int, int, int]]:
    """Прямоугольники краевых полос (left, top, width, height) для полосного захвата."""
    bw = max(1, int(width * band_size))
    bh = max(1, int(height * band_size))
    all_rects = {
        "top": (0, 0, width, bh),
        "bottom": (0, height - bh, width, bh),
        "left": (0, 0, bw, height),
        "right": (width - bw, 0, bw, height),
    }
    return {side: all_rects[side] for side in sides}


def localize_slice(side: str, slc: Slice, width: int, height: int, bw: int, bh: int) -> Slice:
    """Перевод зоны из координат полного кадра в координаты своей краевой полосы."""
    y1, y2, x1, x2 = slc
    if side == "bottom":
        return (y1 - (height - bh), y2 - (height - bh), x1, x2)
    if side == "right":
        return (y1, y2, x1 - (width - bw), x2 - (width - bw))
    return (y1, y2, x1, x2)  # top и left уже локальны


class Engine:
    PREVIEW_INTERVAL_S = 0.3
    PREVIEW_HEIGHT = 180

    def __init__(
        self,
        cfg: Config,
        on_colors: Callable[[np.ndarray], None] | None = None,
        on_fps: Callable[[float], None] | None = None,
        on_backend: Callable[[str], None] | None = None,
        on_frame: Callable[[np.ndarray], None] | None = None,
        backend_factory: Callable[[Config], object] = create_backend,
    ):
        cfg.validate()
        self.cfg = cfg
        self.geom = LedGeometry(cfg)
        self.device = AdalightDevice(cfg)
        self._on_colors = on_colors
        self._on_fps = on_fps
        self._on_backend = on_backend
        self._on_frame = on_frame
        self._preview_frames = cfg.preview_screen
        self._backend_factory = backend_factory
        self._stop = threading.Event()
        self._lock = threading.Lock()

        # живые параметры (могут меняться из GUI-потока)
        self._smooth = cfg.smooth
        self._default_brightness = cfg.brightness
        self._schedule_enabled = cfg.schedule_enabled
        self._rules: list[ScheduleRule] = (
            parse_rules(cfg.schedule) if cfg.schedule_enabled else []
        )
        self._adaptive_enabled = cfg.adaptive_enabled
        self._adaptive_min = cfg.adaptive_min
        self._adaptive_max = cfg.adaptive_max
        self._adaptive_speed = cfg.adaptive_speed

        self._night = cfg.night_mode
        self._color_temp = cfg.color_temp
        self._lamp = {
            "lamp_effect": cfg.lamp_effect,
            "lamp_color": cfg.lamp_color,
            "lamp_gradient": cfg.lamp_gradient,
            "lamp_speed": cfg.lamp_speed,
        }
        self._music = {
            "music_effect": cfg.music_effect,
            "music_color": cfg.music_color,
            "music_gain": cfg.music_gain,
        }
        self._music_dirty = False

        self._lum_smoothed = 0.5  # сглаженная яркость сцены 0..1
        self._applied_brightness: float | None = None
        self._apply_color_temp()

    def _apply_color_temp(self) -> None:
        temp = min(self._color_temp, NIGHT_COLOR_TEMP) if self._night else self._color_temp
        self.device.set_tuning(color_temp=temp)

    def _effective_smooth(self) -> float:
        return max(self._smooth, NIGHT_MIN_SMOOTH) if self._night else self._smooth

    def stop(self) -> None:
        self._stop.set()

    def set_tuning(
        self,
        *,
        gamma: float | None = None,
        brightness: float | None = None,
        saturation: float | None = None,
        smooth: float | None = None,
        schedule_enabled: bool | None = None,
        schedule: list[dict] | None = None,
        adaptive_enabled: bool | None = None,
        adaptive_min: float | None = None,
        adaptive_max: float | None = None,
        adaptive_speed: float | None = None,
        color_temp: int | None = None,
        black_threshold: float | None = None,
        night_mode: bool | None = None,
        lamp_effect: str | None = None,
        lamp_color: str | None = None,
        lamp_gradient: list[dict] | None = None,
        lamp_speed: float | None = None,
        music_effect: str | None = None,
        music_color: str | None = None,
        music_gain: float | None = None,
        preview_screen: bool | None = None,
    ) -> None:
        """Применение «мягких» настроек на лету. schedule — сырой список из конфига."""
        with self._lock:
            if smooth is not None:
                self._smooth = smooth
            if brightness is not None:
                self._default_brightness = brightness
            if schedule_enabled is not None:
                self._schedule_enabled = schedule_enabled
            if schedule is not None:
                self._rules = parse_rules(schedule)
            if adaptive_enabled is not None:
                self._adaptive_enabled = adaptive_enabled
            if adaptive_min is not None:
                self._adaptive_min = adaptive_min
            if adaptive_max is not None:
                self._adaptive_max = adaptive_max
            if adaptive_speed is not None:
                self._adaptive_speed = adaptive_speed
            if color_temp is not None:
                self._color_temp = color_temp
            if night_mode is not None:
                self._night = night_mode
            if preview_screen is not None:
                self._preview_frames = preview_screen
            for key, value in (
                ("lamp_effect", lamp_effect),
                ("lamp_color", lamp_color),
                ("lamp_gradient", lamp_gradient),
                ("lamp_speed", lamp_speed),
            ):
                if value is not None:
                    self._lamp[key] = value
            for key, value in (
                ("music_effect", music_effect),
                ("music_color", music_color),
                ("music_gain", music_gain),
            ):
                if value is not None and self._music[key] != value:
                    self._music[key] = value
                    self._music_dirty = True
            self.device.set_tuning(
                gamma=gamma, saturation=saturation, black_threshold=black_threshold
            )
            self._apply_color_temp()
            self._applied_brightness = None  # форсируем пересчёт итоговой яркости

    def run(self, mode: Mode = "live") -> None:
        if mode == "live":
            self._run_live()
        elif mode == "lamp":
            self._run_lamp()
        elif mode == "music":
            self._run_music()
        elif mode == "chase":
            self._run_chase()
        elif mode == "sides":
            self._run_sides()
        elif mode == "off":
            self._run_off()
        else:
            raise ValueError(f"Неизвестный режим: {mode!r}")

    # ── внутреннее ────────────────────────────────────────────────────────

    def _emit(self, colors: np.ndarray) -> None:
        if self._on_colors is not None:
            self._on_colors(np.asarray(colors, dtype=np.uint8).copy())

    def _effective_brightness(self, raw: np.ndarray | None) -> float:
        """Итоговая яркость: расписание (или дефолт) × адаптивный коэффициент."""
        with self._lock:
            base = self._default_brightness
            if self._schedule_enabled and self._rules:
                base = brightness_at(
                    datetime.datetime.now().time(), self._rules, self._default_brightness
                )
            if self._adaptive_enabled and raw is not None:
                lum = float(raw.mean()) / 255.0
                self._lum_smoothed += (lum - self._lum_smoothed) * self._adaptive_speed
                lo, hi = self._adaptive_min, self._adaptive_max
                base *= lo + (hi - lo) * self._lum_smoothed
            if self._night:
                base *= NIGHT_BRIGHTNESS_FACTOR
        return round(base, 2)  # квантуем, чтобы не перестраивать LUT каждый кадр

    def _apply_brightness(self, raw: np.ndarray | None) -> None:
        eff = self._effective_brightness(raw)
        if eff != self._applied_brightness:
            self.device.set_tuning(brightness=eff)
            self._applied_brightness = eff

    def _run_live(self) -> None:
        backend = self._backend_factory(self.cfg)
        try:
            if self._on_backend is not None:
                note = f" ({backend.fallback_reason})" if backend.fallback_reason else ""
                self._on_backend(f"{type(backend).__name__}{note}")

            w, h = backend.width, backend.height
            slices = self.geom.calculate_slices(w, h)
            sides = [s for s, _, _ in self.geom.points]

            use_bands = backend.supports_bands
            if use_bands:
                bw = max(1, int(w * self.cfg.band_size))
                bh = max(1, int(h * self.cfg.band_size))
                rects = band_rects(w, h, self.cfg.band_size, set(sides))
                local = [
                    localize_slice(sides[i], slc, w, h, bw, bh)
                    for i, slc in enumerate(slices)
                ]

            self.device.connect()

            n = self.cfg.total_leds
            smoothed = np.zeros((n, 3))
            raw = np.empty((n, 3))
            frame_time = 1.0 / self.cfg.target_fps
            fps_t0, fps_n = time.monotonic(), 0
            preview_t = 0.0

            while not self._stop.is_set():
                t0 = time.monotonic()

                got_frame = False
                img = None
                if use_bands:
                    bands = backend.get_bands(rects)
                    for i, (y1, y2, x1, x2) in enumerate(local):
                        reg = bands[sides[i]][y1:y2, x1:x2]
                        raw[i] = reg.mean(axis=(0, 1)) if reg.size else 0.0
                    got_frame = True
                else:
                    img = backend.get_frame()
                    if img is not None:
                        for i, (y1, y2, x1, x2) in enumerate(slices):
                            reg = img[y1:y2, x1:x2]
                            raw[i] = reg.mean(axis=(0, 1)) if reg.size else 0.0
                        got_frame = True

                # уменьшенный кадр для предпросмотра экрана в GUI
                if (
                    self._on_frame is not None
                    and self._preview_frames
                    and t0 - preview_t >= self.PREVIEW_INTERVAL_S
                ):
                    if img is None and use_bands:
                        img = backend.get_frame()
                    if img is not None:
                        step = max(1, img.shape[0] // self.PREVIEW_HEIGHT)
                        self._on_frame(np.ascontiguousarray(img[::step, ::step]))
                        preview_t = t0

                if got_frame:
                    self._apply_brightness(raw)
                    s = self._effective_smooth()
                    smoothed *= s
                    smoothed += raw * (1.0 - s)
                    final = self.device.send_processed(smoothed)
                    self._emit(final)

                fps_n += 1
                now = time.monotonic()
                if now - fps_t0 >= 1.0:
                    if self._on_fps is not None:
                        self._on_fps(fps_n / (now - fps_t0))
                    fps_t0, fps_n = now, 0

                dt = time.monotonic() - t0
                if dt < frame_time:
                    self._stop.wait(frame_time - dt)
        finally:
            self.device.close()
            backend.close()

    def _run_lamp(self) -> None:
        """Режим «лампа»: эффект без захвата экрана. Параметры меняются на лету."""
        self.device.connect()
        try:
            n = self.cfg.total_leds
            frame_time = 1.0 / min(self.cfg.target_fps, 60)
            t0 = time.monotonic()
            while not self._stop.is_set():
                tick = time.monotonic()
                with self._lock:
                    lamp = dict(self._lamp)
                raw = render_lamp(lamp, n, tick - t0)
                self._apply_brightness(None)
                final = self.device.send_processed(raw)
                self._emit(final)
                dt = time.monotonic() - tick
                if dt < frame_time:
                    self._stop.wait(frame_time - dt)
        finally:
            self.device.close()

    def _run_music(self) -> None:
        """Цветомузыка: системный loopback-звук -> спектр/пульс на ленте."""
        from .audio import LoopbackAudio  # импорт при использовании: тянет soundcard

        audio = LoopbackAudio()
        try:
            n = self.cfg.total_leds
            renderer = self._make_music_renderer(n)
            if self._on_backend is not None:
                self._on_backend(f"audio {audio.samplerate} Гц")
            self.device.connect()
            fps_t0, fps_n = time.monotonic(), 0
            while not self._stop.is_set():
                block = audio.read()  # блокирует на ~blocksize/rate (~21 мс)
                with self._lock:
                    if self._music_dirty:
                        renderer = self._make_music_renderer(n)
                        self._music_dirty = False
                raw = renderer.render(block, audio.samplerate)
                self._apply_brightness(None)
                final = self.device.send_processed(raw)
                self._emit(final)

                fps_n += 1
                now = time.monotonic()
                if now - fps_t0 >= 1.0:
                    if self._on_fps is not None:
                        self._on_fps(fps_n / (now - fps_t0))
                    fps_t0, fps_n = now, 0
        finally:
            audio.close()
            self.device.close()

    def _make_music_renderer(self, n: int) -> MusicRenderer:
        return MusicRenderer(
            effect=self._music["music_effect"],
            color=self._music["music_color"],
            gain=self._music["music_gain"],
            n_leds=n,
        )

    def _run_chase(self) -> None:
        self.device.connect()
        try:
            n = self.cfg.total_leds
            i = 0
            while not self._stop.is_set():
                colors = np.full((n, 3), 6, dtype=np.uint8)
                colors[i] = (255, 255, 255)
                self.device.send_raw(colors)
                self._emit(colors)
                i = (i + 1) % n
                self._stop.wait(0.12)
        finally:
            self.device.close()

    def _run_sides(self) -> None:
        colors = np.array(
            [SIDE_TEST_PALETTE[s] for s, _, _ in self.geom.points], dtype=np.uint8
        )
        self.device.connect()
        try:
            while not self._stop.is_set():
                self.device.send_raw(colors)
                self._emit(colors)
                self._stop.wait(0.5)
        finally:
            self.device.close()

    def _run_off(self) -> None:
        self.device.connect()
        self.device.close()  # close() гасит ленту перед закрытием порта
        self._emit(np.zeros((self.cfg.total_leds, 3), dtype=np.uint8))
