"""Бэкенды захвата для Wayland (Hyprland/wlroots): wf-recorder и grim."""

from __future__ import annotations

import collections
import json
import subprocess
import threading
import time

import numpy as np

from .. import subproc
from ..config import Config
from .base import BaseBackend, CaptureError


def hyprland_monitors() -> list[dict]:
    try:
        out = subproc.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True)
    except FileNotFoundError as e:
        raise CaptureError("hyprctl не найден — сессия не Hyprland?") from e
    if out.returncode != 0:
        # причина всегда в stderr: без неё сообщение «код возврата 1» ничего
        # не объясняет (так пряталась подмена libstdc++ из бандла PyInstaller)
        detail = (out.stderr.strip() or out.stdout.strip() or "без вывода").splitlines()[0]
        raise CaptureError(f"hyprctl monitors: код {out.returncode}, {detail}")
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError as e:
        raise CaptureError(f"hyprctl вернул не JSON: {e}") from e


def resolve_output(cfg: Config) -> tuple[str, int, int]:
    """Имя и размер монитора; при пустом cfg.output — первый доступный."""
    monitors = hyprland_monitors()
    if not monitors:
        raise CaptureError("hyprctl не вернул ни одного монитора")
    if not cfg.output:
        m = monitors[0]
        return m["name"], int(m["width"]), int(m["height"])
    # старые версии GUI сохраняли ярлык списка целиком («HDMI-A-1 (1920x1080)»)
    wanted = cfg.output.split(" (")[0].strip()
    for m in monitors:
        if m["name"] == wanted:
            return m["name"], int(m["width"]), int(m["height"])
    names = ", ".join(m["name"] for m in monitors)
    raise CaptureError(f"Монитор {cfg.output!r} не найден. Доступны: {names}")


class WfRecorderBackend(BaseBackend):
    """Потоковый захват через wf-recorder (rawvideo bgr0 в pipe)."""

    FIRST_FRAME_TIMEOUT = 20.0

    def __init__(self, cfg: Config):
        self.output, self.width, self.height = resolve_output(cfg)
        self._fbytes = self.width * self.height * 4
        self._latest: bytes | None = None
        self._alive = True

        cmd = [
            "wf-recorder", "-o", self.output,
            "-c", "rawvideo", "-m", "rawvideo",
            "-x", "bgr0", "-f", "pipe:1",
        ]
        try:
            self._proc = subproc.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError as e:
            raise CaptureError("wf-recorder не установлен") from e

        # stderr держим в кольцевом буфере: выбросить его в DEVNULL значит
        # потерять причину падения, а не читать из трубы — заклинить процесс
        self._errlog: collections.deque[str] = collections.deque(maxlen=10)
        self._errthread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._errthread.start()
        threading.Thread(target=self._reader, daemon=True).start()
        self._wait_for_first_frame()

    def _drain_stderr(self) -> None:
        try:
            for line in self._proc.stderr:
                text = line.decode(errors="replace").strip()
                if text:
                    self._errlog.append(text)
        except Exception:  # noqa: BLE001 — труба закрыта вместе с процессом
            pass

    def _wait_for_first_frame(self) -> None:
        t0 = time.time()
        while self._latest is None:
            if self._proc.poll() is not None:
                self._errthread.join(timeout=0.5)  # дать дочитать причину падения
                detail = "; ".join(self._errlog) or "без вывода"
                raise CaptureError(
                    f"wf-recorder упал при старте (код {self._proc.returncode}): {detail}"
                )
            if not self._alive:
                raise CaptureError("Поток wf-recorder оборвался")
            if time.time() - t0 > self.FIRST_FRAME_TIMEOUT:
                self.close()
                raise CaptureError(
                    "wf-recorder не отдал ни одного кадра: экран статичен? "
                    "Пошевелите мышкой или включите видео."
                )
            time.sleep(0.05)

    def _reader(self) -> None:
        try:
            f = self._proc.stdout
            while self._alive:
                remain = self._fbytes
                chunks = []
                while remain > 0:
                    chunk = f.read(remain)
                    if not chunk:
                        self._alive = False
                        return
                    chunks.append(chunk)
                    remain -= len(chunk)
                self._latest = b"".join(chunks)
        except Exception:
            self._alive = False

    def get_frame(self) -> np.ndarray | None:
        data = self._latest
        if not data or len(data) != self._fbytes:
            return None
        # bgr0 -> RGB
        return np.frombuffer(data, np.uint8).reshape((self.height, self.width, 4))[..., 2::-1]

    def close(self) -> None:
        self._alive = False
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()


class GrimBackend(BaseBackend):
    """Захват однократными снимками grim в уменьшенном масштабе (запасной вариант)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.output, _, _ = resolve_output(cfg)
        first = self._grab()
        self.height, self.width = first.shape[:2]

    def _grab(self) -> np.ndarray:
        try:
            p = subproc.run(
                ["grim", "-o", self.output, "-s", str(self.cfg.grim_scale), "-t", "ppm", "-"],
                capture_output=True,
            )
        except FileNotFoundError as e:
            raise CaptureError("grim не установлен") from e
        if p.returncode != 0:
            raise CaptureError(f"grim упал: {p.stderr.decode(errors='replace')}")
        return self._parse_ppm(p.stdout)

    def get_frame(self) -> np.ndarray | None:
        return self._grab()

    @staticmethod
    def _parse_ppm(data: bytes) -> np.ndarray:
        idx, vals = 2, []
        while len(vals) < 3:
            while idx < len(data) and data[idx : idx + 1].isspace():
                idx += 1
            if data[idx : idx + 1] == b"#":
                while idx < len(data) and data[idx : idx + 1] != b"\n":
                    idx += 1
                continue
            start = idx
            while idx < len(data) and not data[idx : idx + 1].isspace():
                idx += 1
            vals.append(int(data[start:idx]))
        w, h, _ = vals
        idx += 1
        return np.frombuffer(data, np.uint8, count=w * h * 3, offset=idx).reshape((h, w, 3))
