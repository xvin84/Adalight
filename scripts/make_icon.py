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
from PySide6.QtGui import QColor, QImage, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# цвета сторон — как в тесте калибровки: верх/право/низ/лево
SIDE_COLORS = {
    "top": QColor(255, 66, 66),
    "right": QColor(62, 220, 100),
    "bottom": QColor(74, 128, 255),
    "left": QColor(255, 200, 40),
}


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)

    # цветная «лента» по периметру: чёткое кольцо из четырёх сегментов
    ring = QRectF(0.14 * s, 0.14 * s, 0.72 * s, 0.72 * s)
    ring_width = 0.13 * s
    radius = 0.16 * s
    clips = {
        "top": QRectF(0, 0, s, 0.38 * s),
        "bottom": QRectF(0, 0.62 * s, s, 0.38 * s),
        "left": QRectF(0, 0.38 * s, 0.5 * s, 0.24 * s),
        "right": QRectF(0.5 * s, 0.38 * s, 0.5 * s, 0.24 * s),
    }
    p.setBrush(Qt.BrushStyle.NoBrush)
    for side, clip in clips.items():
        p.save()
        p.setClipRect(clip)
        p.setPen(QPen(SIDE_COLORS[side], ring_width, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.FlatCap))
        p.drawRoundedRect(ring, radius, radius)
        p.restore()

    # тёмный «монитор» внутри — вплотную к рамке, без зазора
    screen = QRectF(0.195 * s, 0.195 * s, 0.61 * s, 0.61 * s)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(22, 24, 28))
    p.drawRoundedRect(screen, 0.12 * s, 0.12 * s)

    # лёгкий блик
    p.setBrush(QColor(255, 255, 255, 22))
    p.drawRoundedRect(
        QRectF(0.28 * s, 0.28 * s, 0.44 * s, 0.16 * s), 0.06 * s, 0.06 * s
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
