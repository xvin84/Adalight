"""Профилировщик цикла вывода (фаза 0 работ по производительности)."""

import time

from adalight.profiling import LoopProfiler


def test_profiler_reports_sections_and_fps():
    lines = []
    prof = LoopProfiler(report_every=3, sink=lines.append)
    for _ in range(3):
        prof.begin()
        time.sleep(0.001)
        prof.mark("захват")
        prof.mark("порт")
        prof.frame()
    assert len(lines) == 1
    line = lines[0]
    assert "fps" in line and "захват" in line and "порт" in line and "прочее" in line
    assert "среднее за 3 кадров" in line


def test_profiler_resets_between_reports():
    lines = []
    prof = LoopProfiler(report_every=2, sink=lines.append)
    for _ in range(4):
        prof.begin()
        prof.mark("захват")
        prof.frame()
    assert len(lines) == 2


def test_disabled_profiler_is_silent_and_cheap():
    lines = []
    prof = LoopProfiler(report_every=0, sink=lines.append)
    assert not prof.enabled
    for _ in range(10):
        prof.begin()
        prof.mark("захват")
        prof.frame()
    assert lines == []


def test_from_env(monkeypatch):
    monkeypatch.delenv("ADALIGHT_PROFILE", raising=False)
    assert not LoopProfiler.from_env().enabled
    monkeypatch.setenv("ADALIGHT_PROFILE", "0")
    assert not LoopProfiler.from_env().enabled
    monkeypatch.setenv("ADALIGHT_PROFILE", "1")
    p = LoopProfiler.from_env()
    assert p.enabled and p._every == 120  # «1» — включить с периодом по умолчанию
    monkeypatch.setenv("ADALIGHT_PROFILE", "240")
    p = LoopProfiler.from_env()
    assert p.enabled and p._every == 240
    monkeypatch.setenv("ADALIGHT_PROFILE", "мусор")
    assert LoopProfiler.from_env().enabled  # не валимся, включаем дефолт
