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

from . import events
from .capture import create_backend
from .config import Config, parse_hex_color
from .device import AdalightDevice, DeviceError
from .effects import render_lamp
from .geometry import LedGeometry, Slice
from .pipeline import apply_frame_filters, has_frame_filters
from .profiling import LoopProfiler
from .schedule import ScheduleRule, brightness_at, parse_rules

Mode = Literal["live", "lamp", "music", "chase", "sides", "off"]

# Ночной режим: теплее, темнее, плавнее
NIGHT_COLOR_TEMP = 3400
NIGHT_BRIGHTNESS_FACTOR = 0.6
NIGHT_MIN_SMOOTH = 0.7

# Тесты («стороны», «бегущая точка») шлют кадры на полной скорости тракта —
# это встроенный замер пропускной способности; кап защищает от спина на
# неблокирующих транспортах (WLED/UDP).
TEST_FPS_CAP = 240
CHASE_STEP_S = 0.12       # шаг точки по ленте — визуальный темп, не темп кадров

RECONNECT_INTERVAL_S = 2.0  # пауза между попытками переоткрыть пропавший порт


class _FpsCounter:
    """Реальная частота отправки кадров, усреднённая за секунду.

    frame() — успешно отправленный кадр; poll() — вызывать каждую итерацию,
    чтобы счётчик публиковал и нули (устройство пропало — в UI виден 0 fps).
    """

    def __init__(self, callback: Callable[[float], None] | None):
        self._cb = callback
        self._t0 = time.monotonic()
        self._n = 0

    def frame(self) -> None:
        self._n += 1
        self.poll()

    def poll(self) -> None:
        now = time.monotonic()
        if now - self._t0 >= 1.0:
            if self._cb is not None:
                self._cb(self._n / (now - self._t0))
            self._t0, self._n = now, 0

SIDE_TEST_PALETTE = {
    "top": (255, 0, 0),      # красный
    "right": (0, 255, 0),    # зелёный
    "bottom": (0, 0, 255),   # синий
    "left": (255, 200, 0),   # жёлтый
}

# Среднему цвету зоны хватает сетки 16x16 отсчётов: и полное усреднение зон
# (~35 мс на кадре 1080p), и поштучные reg.mean() по 120 зонам (~5 мс оверхеда
# вызовов) душили конвейер — профиль фазы 0 показал именно этот участок.
ZONE_SAMPLE = 16


class ZoneSampler:
    """Средний цвет всех зон одним обращением к numpy: k×k отсчётов на зону.

    Сетки индексов строятся один раз под известное разрешение; на кадре
    остаётся одно выборочное чтение и один mean — время не зависит от
    разрешения экрана, а цвет совпадает с честным средним с точностью до шума.
    """

    def __init__(self, slices: list[Slice], height: int, width: int, k: int = ZONE_SAMPLE):
        n = len(slices)
        self._ys = np.empty((n, k, 1), dtype=np.intp)
        self._xs = np.empty((n, 1, k), dtype=np.intp)
        for i, (y1, y2, x1, x2) in enumerate(slices):
            ys = np.linspace(y1, max(y1, y2 - 1), k).round().astype(np.intp)
            xs = np.linspace(x1, max(x1, x2 - 1), k).round().astype(np.intp)
            self._ys[i, :, 0] = np.clip(ys, 0, max(height - 1, 0))
            self._xs[i, 0, :] = np.clip(xs, 0, max(width - 1, 0))

    def means(self, img: np.ndarray) -> np.ndarray:
        """Массив (зоны, 3) средних цветов зон кадра."""
        return img[self._ys, self._xs].mean(axis=(1, 2), dtype=np.float64)


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
    KEEPALIVE_S = 3.0        # переслать кадр не реже — плата не заснёт (её порог ~10 с)
    SLEEP_CHANGE_THRESHOLD = 4  # изменение цвета диода меньше — считаем «нет движения»

    def __init__(
        self,
        cfg: Config,
        on_colors: Callable[[np.ndarray], None] | None = None,
        on_fps: Callable[[float], None] | None = None,
        on_backend: Callable[[str], None] | None = None,
        on_frame: Callable[[np.ndarray], None] | None = None,
        on_device: Callable[[bool], None] | None = None,
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
        self._on_device = on_device
        self._preview_frames = cfg.preview_screen
        self._backend_factory = backend_factory
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._profiler = LoopProfiler.from_env()

        # предпросмотр цветов в GUI обновляется реже, чем идут кадры на ленту:
        # глазу в интерфейсе хватает preview_fps, а лента получает полный поток
        self._preview_dt = 1.0 / max(cfg.preview_fps, 1)
        self._preview_colors_t = 0.0

        # потеря устройства на ходу не роняет цикл — ждём и переоткрываем порт
        self._device_ok = True
        self._reconnect_t = 0.0

        # последний кадр, реально ушедший на ленту (после фильтров модов) —
        # его же показываем в предпросмотре, чтобы UI не врал
        self._sent = np.zeros((cfg.total_leds, 3), dtype=np.uint8)

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
        self._sleep_enabled = cfg.sleep_enabled
        self._sleep_timeout_s = cfg.sleep_timeout_s

        self._night = cfg.night_mode
        self._color_temp = cfg.color_temp
        self._lamp = {
            "lamp_effect": cfg.lamp_effect,
            "lamp_color": cfg.lamp_color,
            "lamp_gradient": cfg.lamp_gradient,
            "lamp_speed": cfg.lamp_speed,
            "fire_height": cfg.fire_height,
            "fire_intensity": cfg.fire_intensity,
            "fire_sparks": cfg.fire_sparks,
        }
        self._music = {
            "music_effect": cfg.music_effect,
            "music_color": cfg.music_color,
            "music_gain": cfg.music_gain,
        }

        self._lum_smoothed = 0.5  # сглаженная яркость сцены 0..1
        self._applied_brightness: float | None = None
        self._overlays: list[dict] = []  # вспышки поверх любого режима
        self._apply_color_temp()

    # ── оверлеи: вспышки поверх текущих цветов (плагины, identify) ────────

    def add_overlay(
        self,
        color: str,
        x: float,
        y: float,
        radius: float = 0.25,
        duration: float = 1.5,
        style: str = "ripple",
    ) -> None:
        """Вспышка цветом в точке (x, y) нормированного экрана, затухает за duration.

        style="ripple" — «бульк»: яркая капля в точке и расходящаяся по ленте
        затухающая волна. style="blob" — статичное пятно (старое поведение).
        Потокобезопасно: зовётся из GUI и из потоков плагинов.
        """
        rgb = np.array(parse_hex_color(color), dtype=np.float64)
        dist = np.array(
            [np.hypot(px - x, py - y) for _, px, py in self.geom.points]
        )
        with self._lock:
            if style == "ripple":
                self._overlays.append(
                    {
                        "kind": "ripple",
                        "rgb": rgb,
                        "d": dist,
                        "reach": float(dist.max()) + max(radius, 0.05),
                        "radius": max(radius, 0.05),
                        "t0": time.monotonic(),
                        "dur": duration,
                    }
                )
            else:
                weights = np.exp(-((dist / max(radius, 0.02)) ** 2))
                self._append_blob(rgb, weights, duration)

    def identify(self, index: int, duration: float = 1.5) -> None:
        """Вспыхнуть белым одним диодом — чтобы найти его на ленте."""
        weights = np.zeros(self.cfg.total_leds)
        if 0 <= index < len(weights):
            weights[index] = 1.0
        with self._lock:
            self._append_blob(np.array([255.0, 255.0, 255.0]), weights, duration)

    def _append_blob(self, rgb: np.ndarray, weights: np.ndarray, duration: float) -> None:
        """Добавить статичное пятно. Зовётся под self._lock."""
        self._overlays.append(
            {"kind": "blob", "rgb": rgb, "w": weights, "t0": time.monotonic(), "dur": duration}
        )

    @staticmethod
    def _ripple_weights(o: dict, progress: float) -> np.ndarray:
        """Веса «булька» на момент progress (0..1): капля в точке + бегущее кольцо."""
        d, radius = o["d"], o["radius"]
        # кольцо расходится от точки, замедляясь, и к концу покидает ленту
        ring_r = o["reach"] * (1.0 - (1.0 - progress) ** 2)
        thickness = radius * (0.6 + 0.8 * progress)
        ring = np.exp(-((d - ring_r) / max(thickness, 0.03)) ** 2) * (1.0 - progress) ** 1.4
        # начальный «бульк» — яркая капля в точке, гаснет быстро
        core = np.exp(-((d / max(radius * 0.5, 0.03)) ** 2))
        core_amp = min(progress / 0.08, 1.0) * np.exp(-((progress / 0.22) ** 2))
        return np.clip(core * core_amp + ring, 0.0, 1.0)

    def _apply_overlays(self, colors: np.ndarray) -> np.ndarray:
        if not self._overlays:
            return colors
        now = time.monotonic()
        with self._lock:
            self._overlays = [o for o in self._overlays if now - o["t0"] < o["dur"]]
            active = list(self._overlays)
        if not active:
            return colors
        out = colors.astype(np.float64)
        for o in active:
            progress = (now - o["t0"]) / o["dur"]
            if o["kind"] == "ripple":
                w = self._ripple_weights(o, progress)
            else:
                # быстрое разгорание (первые 12%), затем плавное затухание
                envelope = min(progress / 0.12, 1.0) * (1.0 - progress)
                w = o["w"] * envelope
            k = w[:, None]
            out = out * (1.0 - k) + o["rgb"] * k
        return np.clip(out, 0.0, 255.0).astype(np.uint8)

    def _apply_color_temp(self) -> None:
        temp = min(self._color_temp, NIGHT_COLOR_TEMP) if self._night else self._color_temp
        self.device.set_tuning(color_temp=temp)

    def _effective_smooth(self) -> float:
        return max(self._smooth, NIGHT_MIN_SMOOTH) if self._night else self._smooth

    def _sleeping(self, now: float, last_activity: float) -> bool:
        """Пора ли гасить ленту: сон включён и экран не менялся дольше таймаута."""
        with self._lock:
            return self._sleep_enabled and (now - last_activity) > self._sleep_timeout_s

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
        sleep_enabled: bool | None = None,
        sleep_timeout_s: int | None = None,
        color_temp: int | None = None,
        black_threshold: float | None = None,
        white_balance: tuple[float, float, float] | None = None,
        night_mode: bool | None = None,
        lamp_effect: str | None = None,
        lamp_color: str | None = None,
        lamp_gradient: list[dict] | None = None,
        lamp_speed: float | None = None,
        fire_height: float | None = None,
        fire_intensity: float | None = None,
        fire_sparks: int | None = None,
        music_effect: str | None = None,
        music_color: str | None = None,
        music_gain: float | None = None,
        preview_screen: bool | None = None,
        preview_fps: int | None = None,
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
            if sleep_enabled is not None:
                self._sleep_enabled = sleep_enabled
            if sleep_timeout_s is not None:
                self._sleep_timeout_s = sleep_timeout_s
            if color_temp is not None:
                self._color_temp = color_temp
            if night_mode is not None:
                self._night = night_mode
            if preview_screen is not None:
                self._preview_frames = preview_screen
            if preview_fps is not None:
                self._preview_dt = 1.0 / max(preview_fps, 1)
            for key, value in (
                ("lamp_effect", lamp_effect),
                ("lamp_color", lamp_color),
                ("lamp_gradient", lamp_gradient),
                ("lamp_speed", lamp_speed),
                ("fire_height", fire_height),
                ("fire_intensity", fire_intensity),
                ("fire_sparks", fire_sparks),
            ):
                if value is not None:
                    self._lamp[key] = value
            for key, value in (
                ("music_effect", music_effect),
                ("music_color", music_color),
                ("music_gain", music_gain),
            ):
                if value is not None:
                    self._music[key] = value
            self.device.set_tuning(
                gamma=gamma,
                saturation=saturation,
                black_threshold=black_threshold,
                white_balance=white_balance,
            )
            self._apply_color_temp()
            self._applied_brightness = None  # форсируем пересчёт итоговой яркости

    def run(self, mode: Mode = "live") -> None:
        runner = {
            "live": self._run_live,
            "lamp": self._run_lamp,
            "music": self._run_music,
            "chase": self._run_chase,
            "sides": self._run_sides,
            "off": self._run_off,
        }.get(mode)
        if runner is None:
            raise ValueError(f"Неизвестный режим: {mode!r}")
        events.emit("engine.started", mode=mode)
        try:
            runner()
        finally:
            events.emit("engine.stopped", mode=mode)

    # ── внутреннее ────────────────────────────────────────────────────────

    def _emit(self, colors: np.ndarray, force: bool = False) -> None:
        """Показ цветов наружу. Колбэк GUI троттлится до preview_fps: очередь
        событий Qt и перерисовка в главном потоке не должны душить цикл вывода.
        force — для разовых состояний (гашение), которые нельзя потерять."""
        out = np.asarray(colors, dtype=np.uint8)
        if self._on_colors is not None:
            now = time.monotonic()
            if force or now - self._preview_colors_t >= self._preview_dt:
                self._preview_colors_t = now
                self._on_colors(out.copy())
        if events.has_subscribers("engine.frame"):  # горячий цикл — только если нужно
            events.emit("engine.frame", colors=out.copy())

    def _send(self, colors: np.ndarray) -> bool:
        """Отправка кадра с выживанием при отключении платы.

        Потеря устройства переводит движок в ожидание: кадры пропускаются,
        порт переоткрывается не чаще RECONNECT_INTERVAL_S. Порт открывается
        и закрывается только здесь, в потоке движка (pyserial не потокобезопасен).

        Здесь же кадр проходит фильтры модов («Защита питания» и т.п.) — это
        единственная точка отправки для всех режимов, поэтому фильтры работают
        и в тестах ленты. Отправленный кадр остаётся в self._sent: именно его,
        а не исходный, показывает предпросмотр.
        """
        if not self._device_ok:
            now = time.monotonic()
            if now - self._reconnect_t < RECONNECT_INTERVAL_S:
                return False
            self._reconnect_t = now
            try:
                self.device.connect()
            except DeviceError:
                return False
            self._device_ok = True
            if self._on_device is not None:
                self._on_device(True)
            events.emit("device.restored", port=self.cfg.port)
        out = apply_frame_filters(colors) if has_frame_filters() else colors
        try:
            self.device.send_raw(out)
            self._sent = out
            return True
        except DeviceError:
            self.device.drop()
            self._device_ok = False
            self._reconnect_t = time.monotonic()
            if self._on_device is not None:
                self._on_device(False)
            events.emit("device.lost", port=self.cfg.port)
            return False

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
                band_samplers = []
                for side, (_, _, rw, rh) in rects.items():
                    idx = np.array([i for i, s in enumerate(sides) if s == side])
                    band_samplers.append(
                        (side, idx, ZoneSampler([local[i] for i in idx], rh, rw))
                    )
            else:
                sampler = ZoneSampler(slices, h, w)

            self.device.connect()

            n = self.cfg.total_leds
            smoothed = np.zeros((n, 3))
            raw = np.empty((n, 3))
            frame_time = 1.0 / self.cfg.target_fps
            fps = _FpsCounter(self._on_fps)
            prof = self._profiler
            preview_t = 0.0
            # режим сна / keep-alive (см. _push_live_frame)
            last_final: np.ndarray | None = None
            last_activity = time.monotonic()  # когда экран последний раз менялся
            last_send = 0.0
            asleep = False
            off = np.zeros((n, 3), dtype=np.uint8)

            while not self._stop.is_set():
                prof.begin()
                t0 = time.monotonic()

                got_frame = False
                img = None
                if use_bands:
                    bands = backend.get_bands(rects)
                    prof.mark("захват")
                    for side, idx, smp in band_samplers:
                        raw[idx] = smp.means(bands[side])
                    got_frame = True
                else:
                    img = backend.get_frame()
                    prof.mark("захват")
                    if img is not None:
                        raw[:] = sampler.means(img)
                        got_frame = True
                prof.mark("кадр")

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
                    prof.mark("предпросмотр")

                if got_frame:
                    self._apply_brightness(raw)
                    s = self._effective_smooth()
                    smoothed *= s
                    smoothed += raw * (1.0 - s)
                    final = self._apply_overlays(self.device.process(smoothed))
                    diff = 255 if last_final is None else int(
                        np.abs(final.astype(np.int16) - last_final.astype(np.int16)).max()
                    )
                    if diff > self.SLEEP_CHANGE_THRESHOLD:
                        last_activity = t0  # экран изменился — это активность
                    last_final = final
                    prof.mark("кадр")
                    if self._sleeping(t0, last_activity):
                        if not asleep:  # только что заснули — гасим один раз
                            asleep = self._send(off)
                            prof.mark("порт")
                            if asleep:
                                self._emit(off, force=True)
                    else:
                        asleep = False
                        sent = self._send(final)
                        prof.mark("порт")
                        if sent:
                            fps.frame()
                            last_send = t0
                            self._emit(self._sent)
                            prof.mark("предпросмотр")
                elif last_final is not None:
                    # нового кадра нет (статичный экран на DXGI-захвате)
                    if self._sleeping(t0, last_activity):
                        if not asleep:
                            asleep = self._send(off)
                            if asleep:
                                self._emit(off, force=True)
                    elif t0 - last_send > self.KEEPALIVE_S:
                        # keep-alive: переслать кадр, иначе плата заснёт через ~10 с
                        self._apply_brightness(raw)  # расписание/адаптив могли поменяться
                        final = self._apply_overlays(self.device.process(smoothed))
                        if self._send(final):
                            fps.frame()
                            last_send = t0
                            last_final = final  # для сна сравниваем кадр до фильтров
                            self._emit(self._sent)

                fps.poll()
                dt = time.monotonic() - t0
                if dt < frame_time:
                    self._stop.wait(frame_time - dt)
                    prof.mark("ожидание")
                prof.frame()
        finally:
            self.device.close()
            backend.close()

    def _run_lamp(self) -> None:
        """Режим «лампа»: эффект без захвата экрана. Параметры меняются на лету."""
        self.device.connect()
        try:
            n = self.cfg.total_leds
            frame_time = 1.0 / min(self.cfg.target_fps, 60)
            fps = _FpsCounter(self._on_fps)
            t0 = time.monotonic()
            while not self._stop.is_set():
                tick = time.monotonic()
                with self._lock:
                    lamp = dict(self._lamp)
                raw = render_lamp(lamp, n, tick - t0, self.geom.points)
                self._apply_brightness(None)
                final = self._apply_overlays(self.device.process(raw))
                if self._send(final):
                    fps.frame()
                    self._emit(self._sent)
                fps.poll()
                dt = time.monotonic() - tick
                if dt < frame_time:
                    self._stop.wait(frame_time - dt)
        finally:
            self.device.close()

    def _run_music(self) -> None:
        """Цветомузыка: системный loopback-звук -> эффект из реестра на ленте."""
        from .audio import LoopbackAudio  # импорт при использовании: тянет soundcard
        from .effects import make_music_renderer

        audio = LoopbackAudio()
        try:
            n = self.cfg.total_leds
            with self._lock:
                current_effect = self._music["music_effect"]
            renderer = make_music_renderer(current_effect, n)  # None — эффект-мод выкл.
            if self._on_backend is not None:
                self._on_backend(f"audio {audio.samplerate} Гц")
            self.device.connect()
            off = np.zeros((n, 3), dtype=np.uint8)
            fps = _FpsCounter(self._on_fps)
            while not self._stop.is_set():
                block = audio.read()  # блокирует на ~blocksize/rate (~21 мс)
                with self._lock:
                    music = dict(self._music)
                if music["music_effect"] != current_effect:  # эффект сменился
                    current_effect = music["music_effect"]
                    renderer = make_music_renderer(current_effect, n)
                if renderer is None:
                    if self._send(off):
                        self._emit(off)
                else:
                    raw = renderer.render(block, audio.samplerate, music)
                    self._apply_brightness(None)
                    final = self._apply_overlays(self.device.process(raw))
                    if self._send(final):
                        fps.frame()
                        self._emit(self._sent)
                fps.poll()
        finally:
            audio.close()
            self.device.close()

    def _run_chase(self) -> None:
        """Тест «бегущая точка»: точка идёт по ленте в темпе CHASE_STEP_S, а кадры
        уходят на полной скорости тракта — счётчик fps показывает реальную
        пропускную способность без внешних скриптов."""
        self.device.connect()
        try:
            n = self.cfg.total_leds
            frame_time = 1.0 / TEST_FPS_CAP
            fps = _FpsCounter(self._on_fps)
            t_start = time.monotonic()
            colors = np.full((n, 3), 6, dtype=np.uint8)
            lit = 0
            while not self._stop.is_set():
                t0 = time.monotonic()
                i = int((t0 - t_start) / CHASE_STEP_S) % n
                colors[lit] = 6
                colors[i] = (255, 255, 255)
                lit = i
                if self._send(colors):
                    fps.frame()
                    self._emit(self._sent)
                fps.poll()
                dt = time.monotonic() - t0
                if dt < frame_time:
                    self._stop.wait(frame_time - dt)
        finally:
            self.device.close()

    def _run_sides(self) -> None:
        """Тест сторон: цвета статичны, но кадры идут на полной скорости тракта —
        как и «бегущая точка», это встроенный замер частоты вывода."""
        colors = np.array(
            [SIDE_TEST_PALETTE[s] for s, _, _ in self.geom.points], dtype=np.uint8
        )
        self.device.connect()
        try:
            frame_time = 1.0 / TEST_FPS_CAP
            fps = _FpsCounter(self._on_fps)
            while not self._stop.is_set():
                t0 = time.monotonic()
                if self._send(colors):
                    fps.frame()
                    self._emit(self._sent)
                fps.poll()
                dt = time.monotonic() - t0
                if dt < frame_time:
                    self._stop.wait(frame_time - dt)
        finally:
            self.device.close()

    def _run_off(self) -> None:
        self.device.connect()
        self.device.close()  # close() гасит ленту перед закрытием порта
        self._emit(np.zeros((self.cfg.total_leds, 3), dtype=np.uint8))
