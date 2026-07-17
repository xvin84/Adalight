"""Плагин «Вспышки уведомлений»: Telegram — голубая, Discord — фиолетовая.

Windows: слушатель уведомлений WinRT (нужно разрешение в «Параметры →
Конфиденциальность → Уведомления»). Linux: мониторинг DBus-уведомлений
(экспериментально).
"""

from __future__ import annotations

import subprocess
import sys
import threading

DEFAULT_SETTINGS = {
    "enabled": False,
    "x": 0.85,          # позиция вспышки на экране (0..1)
    "y": 0.9,
    "radius": 0.3,      # размер пятна
    "telegram_color": "#4fc3f7",
    "discord_color": "#7c4dff",
}


def match_rule(app_name: str, settings: dict) -> str | None:
    """Цвет вспышки по имени приложения (None — не наше уведомление)."""
    low = app_name.lower()
    if "telegram" in low:
        return settings.get("telegram_color", DEFAULT_SETTINGS["telegram_color"])
    if "discord" in low:
        return settings.get("discord_color", DEFAULT_SETTINGS["discord_color"])
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

    def _flash(self, color: str) -> None:
        s = self._settings
        self._api.trigger_flash(
            color,
            float(s.get("x", 0.85)),
            float(s.get("y", 0.9)),
            float(s.get("radius", 0.3)),
            duration=1.6,
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
                        app_name = n.app_info.display_info.display_name
                    except OSError:
                        continue
                    color = match_rule(app_name or "", self._settings)
                    if color:
                        self._flash(color)
                first_pass = False
                await asyncio.sleep(2.0)

        asyncio.run(watch())

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

        expecting_app = False
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            stripped = line.strip()
            if "member=Notify" in stripped:
                expecting_app = True  # первый string после заголовка — имя приложения
                continue
            if expecting_app and stripped.startswith('string "'):
                app_name = stripped[len('string "') : -1]
                expecting_app = False
                color = match_rule(app_name, self._settings)
                if color:
                    self._flash(color)


def create_plugin() -> NotificationsPlugin:
    return NotificationsPlugin()
