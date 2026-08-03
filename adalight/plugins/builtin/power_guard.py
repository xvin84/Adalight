"""Встроенный мод «Защита питания».

Лента съедает больше, чем даёт USB: у WS2812B каждый канал диода берёт ~20 мА
на полной яркости, то есть белый диод — 60 мА, и восьми диодов уже хватает,
чтобы выбрать полампера. Ток идёт через защитный диод и дорожки платы, поэтому
на ярких сценах греется именно плата — вплоть до просадки и перезагрузки.

Мод считает ток по каждому кадру перед отправкой и, когда тот выше бюджета
источника, притушивает всю ленту, пока не уложится — но не ниже заданной
минимальной яркости. Ток линеен по значению байта, поэтому нужный коэффициент
считается сразу, без пошагового подбора. Обратной связи здесь нет: оценка
берётся с исходного кадра, а не с уже приглушённого, — поэтому регулятор не
может войти в автоколебания. Вниз он идёт мгновенно (лимит не превышается
никогда), вверх — плавно, за время «возврата яркости».

Это оценка, а не измерение: она верна ровно настолько, насколько верны
паспортные токи в настройках. Мод снижает риск на ярких сценах, но не заменяет
внешнее питание и ничего не может, когда приложение не запущено.
"""

from __future__ import annotations

import math
import threading
import time

import numpy as np

# WS2812B (5 В): 20 мА на канал при значении 255 — белый диод берёт 60 мА.
# Чип потребляет ещё около 1 мА просто так, даже на чёрном кадре: на 60 диодах
# это уже 60 мА, которые никаким затемнением не убрать.
DEFAULT_CHANNEL_MA = 20.0
DEFAULT_IDLE_MA = 1.0
# Сама плата с USB-мостом (Nano/Uno) — её ток вычитается из бюджета порта.
DEFAULT_BOARD_MA = 30.0
USB2_BUDGET_MA = 500  # обычный USB-порт; USB 3.0 — 900

DEFAULT_SETTINGS = {
    "enabled": False,
    "budget_ma": USB2_BUDGET_MA,
    "headroom": 10,          # запас безопасности, % от бюджета
    # Ниже этой доли яркость не опускаем. Дефолт низкий не случайно: на длинной
    # ленте от USB бюджет упирается именно в минимум, и при высоком пороге мод
    # перестаёт защищать (лимит превышается, статус показывает «минимум»).
    "min_brightness": 0.05,
    "release_s": 1.5,        # за сколько яркость возвращается, когда ток упал
    "channel_ma": DEFAULT_CHANNEL_MA,
    "idle_ma": DEFAULT_IDLE_MA,
    "board_ma": DEFAULT_BOARD_MA,
    "attack_s": 0.0,         # 0 — притушить мгновенно (лимит не превышается)
}

# Статус в шину: не чаще этого, пока состояние не меняется (кадров до 100/с).
REPORT_INTERVAL_S = 0.5
MAX_DT_S = 1.0  # пауза между кадрами больше — считаем как MAX_DT_S (сон, стоп)


def limit_ma(settings: dict) -> float:
    """Сколько миллиампер можно отдать ленте: бюджет минус запас и плата."""
    budget = float(settings.get("budget_ma", USB2_BUDGET_MA))
    headroom = float(settings.get("headroom", 10)) / 100.0
    board = float(settings.get("board_ma", DEFAULT_BOARD_MA))
    return max(budget * (1.0 - headroom) - board, 0.0)


def strip_current_ma(colors: np.ndarray, settings: dict) -> float:
    """Оценка тока ленты (мА) для кадра RGB-байт (N, 3).

    Средний ток канала пропорционален скважности ШИМ, а её задаёт сам байт —
    поэтому сумма байтов кадра прямо переводится в миллиамперы. Плюс ток покоя
    чипов, который от цвета не зависит.
    """
    channel = float(settings.get("channel_ma", DEFAULT_CHANNEL_MA))
    idle = float(settings.get("idle_ma", DEFAULT_IDLE_MA))
    lit = float(np.sum(colors, dtype=np.float64)) / 255.0 * channel
    return lit + len(colors) * idle


def target_gain(colors: np.ndarray, settings: dict) -> float:
    """Во сколько раз нужно приглушить кадр, чтобы уложиться в лимит (0..1).

    Ток покоя не масштабируется — вычитаем его из лимита и делим остаток на
    ток «света». Если лимита не хватает даже на покой, отдаём минимальную
    яркость: гасить ленту целиком мод не вправе, это решение пользователя.
    """
    minimum = float(settings.get("min_brightness", DEFAULT_SETTINGS["min_brightness"]))
    channel = float(settings.get("channel_ma", DEFAULT_CHANNEL_MA))
    idle = float(settings.get("idle_ma", DEFAULT_IDLE_MA))
    lit = float(np.sum(colors, dtype=np.float64)) / 255.0 * channel
    if lit <= 0.0:
        return 1.0
    room = limit_ma(settings) - len(colors) * idle
    if room <= 0.0:
        return minimum
    return min(max(room / lit, minimum), 1.0)


def _smoothing(dt: float, tau: float) -> float:
    """Доля пути к цели за время dt при постоянной времени tau (0 — мгновенно)."""
    if tau <= 0.0:
        return 1.0
    return 1.0 - math.exp(-dt / tau)


class PowerGuardPlugin:
    name = "power_guard"
    title = "Защита питания"
    description = (
        "Считает ток ленты по кадру и плавно притушивает её, когда он выше "
        "бюджета питания — чтобы яркие сцены не грели плату без внешнего блока."
    )
    version = "1.0"

    settings_schema = [
        {
            "type": "note",
            "label": "Ток ленты оценивается по кадру перед отправкой. Пока он "
                     "выше бюджета, яркость всей ленты снижается — но не ниже "
                     "минимальной. Это расчёт по паспортным токам, а не "
                     "измерение: он не заменяет внешнее питание.",
        },
        {
            "key": "budget_ma", "type": "int", "label": "Бюджет питания, мА",
            "min": 100, "max": 20000, "step": 100, "default": USB2_BUDGET_MA,
        },
        {
            "type": "note",
            "label": "USB 2.0 — 500 мА, USB 3.0 — 900 мА. С внешним блоком "
                     "укажите его ток.",
        },
        {
            "key": "headroom", "type": "int", "label": "Запас безопасности, %",
            "min": 0, "max": 50, "step": 5, "default": 10,
        },
        {
            "key": "min_brightness", "type": "float", "label": "Минимальная яркость",
            "min": 0.0, "max": 1.0, "step": 0.05, "default": 0.05,
        },
        {
            "type": "note",
            "label": "Ниже минимума мод не опускает яркость даже ценой "
                     "превышения бюджета — пока он в это упирается, в статусе "
                     "видна пометка «минимум».",
        },
        {
            "key": "release_s", "type": "float", "label": "Возврат яркости, с",
            "min": 0.1, "max": 10.0, "step": 0.5, "default": 1.5,
        },
        {
            "key": "channel_ma", "type": "float", "advanced": True,
            "label": "Ток канала диода при 255, мА",
            "min": 1.0, "max": 100.0, "step": 1.0, "default": DEFAULT_CHANNEL_MA,
        },
        {
            "key": "idle_ma", "type": "float", "advanced": True,
            "label": "Ток покоя диода, мА",
            "min": 0.0, "max": 10.0, "step": 0.1, "default": DEFAULT_IDLE_MA,
        },
        {
            "key": "board_ma", "type": "float", "advanced": True,
            "label": "Потребление платы, мА",
            "min": 0.0, "max": 500.0, "step": 5.0, "default": DEFAULT_BOARD_MA,
        },
        {
            "key": "attack_s", "type": "float", "advanced": True,
            "label": "Плавность срабатывания, с",
            "min": 0.0, "max": 2.0, "step": 0.05, "default": 0.0,
        },
        {
            "type": "note", "advanced": True,
            "label": "По умолчанию — паспорт WS2812B на 5 В: 20 мА на канал "
                     "(белый диод — 60 мА) и ~1 мА покоя. Для SK6812 RGBW и "
                     "WS2815 на 12 В значения другие, смотрите даташит ленты.",
        },
    ]

    def __init__(self) -> None:
        self._api = None
        self._lock = threading.Lock()
        self._settings = dict(DEFAULT_SETTINGS)
        self._gain = 1.0
        self._last_t: float | None = None
        self._report_t = 0.0
        self._was_limited = False

    def register(self, api) -> None:
        # priority 90 — после фильтров, меняющих картинку: ограничивать надо
        # то, что уйдёт в ленту на самом деле
        api.register_frame_filter(self.name, self.filter_frame, priority=90)

    def start(self, api, settings: dict) -> None:
        with self._lock:
            self._api = api
            self._settings = {**DEFAULT_SETTINGS, **settings}
            self._reset()

    def stop(self) -> None:
        with self._lock:
            self._reset()

    def _reset(self) -> None:
        """Сброс регулятора. Зовётся под self._lock."""
        self._gain = 1.0
        self._last_t = None
        self._was_limited = False

    def filter_frame(self, colors: np.ndarray) -> np.ndarray | None:
        """Приглушить кадр до бюджета тока. None — кадр не менялся."""
        now = time.monotonic()
        with self._lock:
            settings = self._settings
            target = target_gain(colors, settings)
            dt = MAX_DT_S if self._last_t is None else min(now - self._last_t, MAX_DT_S)
            self._last_t = now
            # вниз — с постоянной «срабатывания» (по умолчанию 0, то есть сразу:
            # так лимит не превышается вовсе), вверх — за время «возврата»
            tau = float(
                settings.get("attack_s", 0.0) if target < self._gain
                else settings.get("release_s", 1.5)
            )
            self._gain += (target - self._gain) * _smoothing(dt, tau)
            gain = self._gain
            api = self._api
            limited = gain < 0.999
            report = None
            if limited or self._was_limited:
                if limited != self._was_limited or now - self._report_t >= REPORT_INTERVAL_S:
                    self._report_t = now
                    self._was_limited = limited
                    report = {
                        "gain": round(gain, 3),
                        "current_ma": round(strip_current_ma(colors, settings) * gain, 1),
                        "limit_ma": round(limit_ma(settings), 1),
                        "limited": limited,
                        "floored": gain <= float(
                            settings.get(
                                "min_brightness", DEFAULT_SETTINGS["min_brightness"]
                            )
                        ),
                    }
        if report is not None and api is not None:
            api.emit("power.status", **report)
        if gain >= 0.999:
            return None
        # усечение (а не округление) — при защите ошибка в меньшую сторону
        return (colors * gain).astype(np.uint8)


def create_plugin() -> PowerGuardPlugin:
    return PowerGuardPlugin()
