"""Генерация иконки приложения: assets/icon.png + assets/icon.ico.

Запуск: uv run python scripts/make_icon.py
ICO собирается вручную как контейнер PNG-кадров (поддерживается Windows Vista+).
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "assets"

GLOWS = [
    ((0.22, 0.22), QColor(255, 64, 64)),    # верх-лево: красный
    ((0.78, 0.22), QColor(64, 255, 96)),    # верх-право: зелёный
    ((0.22, 0.78), QColor(255, 208, 48)),   # низ-лево: жёлтый
    ((0.78, 0.78), QColor(72, 128, 255)),   # низ-право: синий
]


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)

    # мягкое свечение по углам
    for (cx, cy), color in GLOWS:
        grad = QRadialGradient(cx * s, cy * s, 0.34 * s)
        grad.setColorAt(0.0, color)
        c2 = QColor(color)
        c2.setAlpha(0)
        grad.setColorAt(1.0, c2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawEllipse(QRectF((cx - 0.34) * s, (cy - 0.34) * s, 0.68 * s, 0.68 * s))

    # тёмный «монитор» поверх свечения
    screen = QRectF(0.22 * s, 0.22 * s, 0.56 * s, 0.56 * s)
    p.setBrush(QColor(22, 24, 28))
    p.drawRoundedRect(screen, 0.09 * s, 0.09 * s)

    # блик на экране
    p.setBrush(QColor(255, 255, 255, 18))
    p.drawRoundedRect(
        QRectF(0.26 * s, 0.26 * s, 0.48 * s, 0.2 * s), 0.05 * s, 0.05 * s
    )
    p.end()
    return img


def image_to_png_bytes(img: QImage) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path: Path, images: list[QImage]) -> None:
    """ICO-контейнер из PNG-кадров: header + directory + данные."""
    blobs = [image_to_png_bytes(img) for img in images]
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    offset = len(header) + 16 * len(images)
    for img, blob in zip(images, blobs, strict=True):
        w = img.width() if img.width() < 256 else 0  # 0 означает 256
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blobs))


def main() -> None:
    QApplication(sys.argv)
    ASSETS.mkdir(exist_ok=True)
    sizes = (256, 64, 48, 32, 16)
    images = [render(s) for s in sizes]
    images[0].save(str(ASSETS / "icon.png"))
    write_ico(ASSETS / "icon.ico", images)
    print(f"OK: {ASSETS / 'icon.png'}, {ASSETS / 'icon.ico'}")


if __name__ == "__main__":
    main()
