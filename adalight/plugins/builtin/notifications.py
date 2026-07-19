"""Плагин «Вспышки уведомлений»: Telegram — голубая, Discord — фиолетовая.

Windows: слушатель уведомлений WinRT (нужно разрешение в «Параметры →
Конфиденциальность → Уведомления»). Linux: мониторинг DBus-уведомлений
(экспериментально).
"""

from __future__ import annotations

import colorsys
import os
import subprocess
import sys
import threading

import numpy as np

DEFAULT_SETTINGS = {
    "enabled": False,
    "x": 0.85,          # позиция вспышки на экране (0..1)
    "y": 0.9,
    "radius": 0.3,      # размер пятна
    "flash_style": "ripple",  # «бульк» с волной (ripple) или статичное пятно (blob)
    "telegram_color": "#4fc3f7",
    "discord_color": "#7c4dff",
    "any_app": False,   # вспыхивать на любые уведомления цветом иконки приложения
}

FALLBACK_ACCENT = "#6c8cff"  # если цвет иконки вычислить не удалось


def match_rule(app_name: str, settings: dict) -> str | None:
    """Цвет вспышки по имени приложения (None — нет специального правила)."""
    low = app_name.lower()
    if "telegram" in low:
        return settings.get("telegram_color", DEFAULT_SETTINGS["telegram_color"])
    if "discord" in low:
        return settings.get("discord_color", DEFAULT_SETTINGS["discord_color"])
    return None


def icon_accent_color(pixels: np.ndarray) -> str | None:
    """Акцентный цвет из RGBA-пикселей иконки: средний цвет, подтянутый до сочного.

    Средний цвет иконок часто грязноват — поднимаем насыщенность и яркость,
    чтобы вспышка на ленте читалась. Прозрачные пиксели не участвуют.
    """
    px = np.asarray(pixels, dtype=np.float64)
    if px.ndim != 2 or px.shape[1] != 4:
        return None
    opaque = px[px[:, 3] > 128]
    if len(opaque) == 0:
        return None
    r, g, b = (opaque[:, :3].mean(axis=0) / 255.0).tolist()
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s = max(s, 0.65)
    v = max(v, 0.9)
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def accent_from_image_bytes(data: bytes) -> str | None:
    """Декодирует картинку (QImage безопасен вне GUI-потока) и берёт акцент."""
    try:
        from PySide6.QtGui import QImage

        img = QImage.fromData(data)
        if img.isNull():
            return None
        img = img.convertToFormat(QImage.Format.Format_RGBA8888).scaled(24, 24)
        w, h, bpl = img.width(), img.height(), img.bytesPerLine()
        buf = np.frombuffer(bytes(img.constBits()), np.uint8)
        return icon_accent_color(buf.reshape(h, bpl)[:, : w * 4].reshape(-1, 4))
    except Exception:  # noqa: BLE001 — цвет иконки — необязательное украшение
        return None


class NotificationsPlugin:
    name = "notifications"
    title = "Вспышки уведомлений"
    description = (
        "Уведомление из Telegram — голубая вспышка на ленте, из Discord — "
        "фиолетовая. Позиция и размер настраиваются. На Windows потребуется "
        "разрешить доступ к уведомлениям (Параметры → Конфиденциальность)."
    )

    def __init__(self) -> None:
        self._api = None
        self._settings: dict = dict(DEFAULT_SETTINGS)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None
        self._icon_colors: dict[str, str | None] = {}  # кэш цвета по имени приложения

    # ── жизненный цикл ────────────────────────────────────────────────────

    def start(self, api, settings: dict) -> None:
        self._api = api
        self._settings = {**DEFAULT_SETTINGS, **settings}
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._proc is not None:
            try:
                self._proc.terminate()
            except OSError:
                pass
            self._proc = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def _flash(self, color: str, app: str = "") -> None:
        # эмитим событие на шину — другие моды могут реагировать на уведомления,
        # не завися от нас; вспышка на ленте — это уже действие
        self._api.emit("notification.received", app=app, color=color)
        s = self._settings
        self._api.trigger_flash(
            color,
            float(s.get("x", 0.85)),
            float(s.get("y", 0.9)),
            float(s.get("radius", 0.3)),
            duration=1.6,
            style=str(s.get("flash_style", "ripple")),
        )

    def _run(self) -> None:
        try:
            if sys.platform == "win32":
                self._run_windows()
            else:
                self._run_linux()
        except Exception as e:  # noqa: BLE001 — ошибки потока наружу как уведомление
            self._api.notify("Вспышки уведомлений", f"Плагин остановлен: {e}")

    # ── Windows: WinRT UserNotificationListener ──────────────────────────

    def _run_windows(self) -> None:
        import asyncio

        from winrt.windows.ui.notifications import NotificationKinds
        from winrt.windows.ui.notifications.management import (
            UserNotificationListener,
            UserNotificationListenerAccessStatus,
        )

        async def watch() -> None:
            listener = UserNotificationListener.current
            status = await listener.request_access_async()
            if status != UserNotificationListenerAccessStatus.ALLOWED:
                self._api.notify(
                    "Вспышки уведомлений",
                    "Нет доступа к уведомлениям Windows. Разрешите его: "
                    "Параметры → Конфиденциальность → Уведомления → Adalight.",
                )
                return
            seen: set[int] = set()
            first_pass = True
            while not self._stop.is_set():
                notifications = await listener.get_notifications_async(
                    NotificationKinds.TOAST
                )
                for n in notifications:
                    if n.id in seen:
                        continue
                    seen.add(n.id)
                    if first_pass:
                        continue  # старые уведомления при запуске не вспыхивают
                    try:
                        app_name = n.app_info.display_info.display_name or ""
                    except OSError:
                        continue
                    color = match_rule(app_name, self._settings)
                    if color is None and self._settings.get("any_app"):
                        color = await self._windows_app_accent(n.app_info, app_name)
                    if color:
                        self._flash(color, app_name)
                first_pass = False
                await asyncio.sleep(2.0)

        asyncio.run(watch())

    async def _windows_app_accent(self, app_info, app_name: str) -> str:
        """Акцентный цвет из иконки приложения (кэшируется по имени)."""
        if app_name in self._icon_colors:
            return self._icon_colors[app_name] or FALLBACK_ACCENT
        color = None
        try:
            from winrt.windows.foundation import Size
            from winrt.windows.storage.streams import DataReader

            ref = app_info.display_info.get_logo(Size(48, 48))
            stream = await ref.open_read_async()
            reader = DataReader(stream.get_input_stream_at(0))
            size = int(stream.size)
            await reader.load_async(size)
            data = bytes(bytearray(reader.read_buffer(size)))
            color = accent_from_image_bytes(data)
        except Exception:  # noqa: BLE001 — нет иконки/доступа: вспыхнем дефолтом
            color = None
        self._icon_colors[app_name] = color
        return color or FALLBACK_ACCENT

    # ── Linux: мониторинг DBus (экспериментально) ─────────────────────────

    def _run_linux(self) -> None:
        cmd = [
            "dbus-monitor",
            "--session",
            "interface='org.freedesktop.Notifications',member='Notify'",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            )
        except FileNotFoundError as e:
            raise RuntimeError("dbus-monitor не установлен") from e

        # после заголовка Notify первые два string-аргумента — имя и иконка
        pending: list[str] | None = None
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            stripped = line.strip()
            if "member=Notify" in stripped:
                pending = []
                continue
            if pending is not None and stripped.startswith('string "'):
                pending.append(stripped[len('string "') : -1])
                if len(pending) < 2:
                    continue
                app_name, app_icon = pending
                pending = None
                color = match_rule(app_name, self._settings)
                if color is None and self._settings.get("any_app"):
                    color = self._linux_app_accent(app_name, app_icon)
                if color:
                    self._flash(color, app_name)

    def _linux_app_accent(self, app_name: str, app_icon: str) -> str:
        """Цвет из иконки: работает, если в Notify передан путь к файлу картинки."""
        if app_name in self._icon_colors:
            return self._icon_colors[app_name] or FALLBACK_ACCENT
        color = None
        if app_icon and os.path.isfile(app_icon):
            try:
                with open(app_icon, "rb") as f:
                    color = accent_from_image_bytes(f.read())
            except OSError:
                color = None
        self._icon_colors[app_name] = color
        return color or FALLBACK_ACCENT


def create_plugin() -> NotificationsPlugin:
    return NotificationsPlugin()
