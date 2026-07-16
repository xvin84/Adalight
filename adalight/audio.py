"""Захват системного звука (loopback) для цветомузыки.

Использует библиотеку soundcard: WASAPI loopback на Windows,
PulseAudio/PipeWire-monitor на Linux.
"""

from __future__ import annotations

import numpy as np


class AudioError(RuntimeError):
    pass


class LoopbackAudio:
    """Блокирующее чтение того, что сейчас играет в динамиках."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 1024):
        try:
            import soundcard as sc
        except Exception as e:  # noqa: BLE001 — на части систем падает не ImportError
            raise AudioError(f"Библиотека soundcard недоступна: {e}") from e

        self.samplerate = samplerate
        self.blocksize = blocksize
        try:
            speaker = sc.default_speaker()
            mic = sc.get_microphone(str(speaker.name), include_loopback=True)
            self._recorder = mic.recorder(samplerate=samplerate, blocksize=blocksize)
            self._recorder.__enter__()
        except Exception as e:  # noqa: BLE001
            raise AudioError(
                f"Loopback-захват звука недоступен ({e}). "
                "Проверьте, что выбрано устройство вывода звука."
            ) from e

    def read(self) -> np.ndarray:
        """Следующий блок как моно float32 (blocksize,). Блокирует на ~blocksize/rate."""
        data = self._recorder.record(numframes=self.blocksize)
        return data.mean(axis=1) if data.ndim > 1 else data

    def close(self) -> None:
        try:
            self._recorder.__exit__(None, None, None)
        except Exception:
            pass
