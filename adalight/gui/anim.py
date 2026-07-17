"""Микроанимации интерфейса: появления, выезд тостов, пульсация индикатора.

Все анимации короткие (180–260 мс) и с мягкими кривыми — интерфейс должен
ощущаться живым, а не медленным.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

_DELETE = QAbstractAnimation.DeletionPolicy.DeleteWhenStopped


def fade_in(widget: QWidget, duration: int = 180) -> None:
    """Плавное появление виджета; эффект снимается по завершении,
    чтобы не замедлять дальнейшую отрисовку."""
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start(_DELETE)


def slide_fade_in(widget: QWidget, end_pos: QPoint, duration: int = 220) -> None:
    """Появление с лёгким выездом снизу (для тостов)."""
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    group = QParallelAnimationGroup(widget)

    fade = QPropertyAnimation(effect, b"opacity", widget)
    fade.setDuration(duration)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)

    slide = QPropertyAnimation(widget, b"pos", widget)
    slide.setDuration(duration)
    slide.setStartValue(end_pos + QPoint(0, 14))
    slide.setEndValue(end_pos)
    slide.setEasingCurve(QEasingCurve.Type.OutCubic)

    group.addAnimation(fade)
    group.addAnimation(slide)
    group.start(_DELETE)


def fade_out_and_delete(widget: QWidget, duration: int = 260) -> None:
    """Растворение и удаление (для тостов)."""
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(effect.opacity())
    anim.setEndValue(0.0)
    anim.finished.connect(widget.deleteLater)
    anim.start(_DELETE)


def make_pulse(widget: QWidget, duration: int = 1400) -> QPropertyAnimation:
    """Бесконечная пульсация прозрачности (индикатор «работает»).

    Возвращает не запущенную анимацию: .start() / .stop() — у вызывающего.
    """
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(1.0)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setLoopCount(-1)
    anim.setKeyValueAt(0.0, 1.0)
    anim.setKeyValueAt(0.5, 0.35)
    anim.setKeyValueAt(1.0, 1.0)
    anim.setEasingCurve(QEasingCurve.Type.InOutSine)
    return anim
