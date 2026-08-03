"""Реестр фильтров кадра: порядок, снятие по моду, изоляция ошибок."""

import numpy as np
import pytest

from adalight import pipeline


@pytest.fixture(autouse=True)
def _clean_registry():
    for spec in pipeline.frame_filters():
        pipeline.unregister_source(spec.source)
    yield
    for spec in pipeline.frame_filters():
        pipeline.unregister_source(spec.source)


def frame(value: int = 100, n: int = 4) -> np.ndarray:
    return np.full((n, 3), value, dtype=np.uint8)


def test_no_filters_is_free():
    assert not pipeline.has_frame_filters()
    src = frame()
    assert pipeline.apply_frame_filters(src) is src  # без копирования кадра


def test_filter_changes_frame():
    pipeline.register_frame_filter("half", lambda c: c // 2, source="mod")
    assert pipeline.has_frame_filters()
    out = pipeline.apply_frame_filters(frame(100))
    assert out.dtype == np.uint8
    assert np.all(out == 50)


def test_filters_run_in_priority_order():
    order: list[str] = []

    def make(tag):
        def fn(colors):
            order.append(tag)
            return colors

        return fn

    pipeline.register_frame_filter("late", make("late"), priority=90, source="mod")
    pipeline.register_frame_filter("early", make("early"), priority=10, source="mod")
    pipeline.apply_frame_filters(frame())
    assert order == ["early", "late"]


def test_none_means_unchanged():
    pipeline.register_frame_filter("noop", lambda c: None, source="mod")
    out = pipeline.apply_frame_filters(frame(70))
    assert np.all(out == 70)


def test_broken_filter_does_not_break_output():
    """Мод с ошибкой пропускается: подсветка не должна гаснуть из-за плагина."""

    def boom(colors):
        raise RuntimeError("плагин сломался")

    pipeline.register_frame_filter("boom", boom, priority=10, source="bad")
    pipeline.register_frame_filter("half", lambda c: c // 2, priority=20, source="mod")
    out = pipeline.apply_frame_filters(frame(100))
    assert np.all(out == 50)


def test_filter_result_is_clipped_to_bytes():
    pipeline.register_frame_filter("boost", lambda c: c * 4.0, source="mod")
    out = pipeline.apply_frame_filters(frame(100))
    assert out.dtype == np.uint8
    assert np.all(out == 255)


def test_unregister_source_removes_only_its_filters():
    pipeline.register_frame_filter("a", lambda c: c, source="one")
    pipeline.register_frame_filter("b", lambda c: c, source="two")
    pipeline.unregister_source("one")
    assert [s.id for s in pipeline.frame_filters()] == ["b"]
