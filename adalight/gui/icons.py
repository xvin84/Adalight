"""SVG-иконки интерфейса: встроены в код, рендерятся в нужном цвете.

Иконки — стилистика тонких линий (stroke 1.8, скруглённые концы), 24x24.
Цвет подставляется вместо currentColor, поэтому один набор работает
в обеих темах и в выделенном состоянии.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_WRAP = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
    'stroke-linejoin="round">{body}</svg>'
)

_BODIES: dict[str, str] = {
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/>'
               '<path d="M9 20h6M12 16v4"/>',
    "chip": '<rect x="7" y="7" width="10" height="10" rx="2"/>'
            '<path d="M9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4"/>',
    "sliders": '<path d="M4 6h16M4 12h16M4 18h16"/>'
               '<circle cx="9" cy="6" r="2.2"/><circle cx="15" cy="12" r="2.2"/>'
               '<circle cx="7" cy="18" r="2.2"/>',
    "sun": '<circle cx="12" cy="12" r="4"/>'
           '<path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2'
           'M5 5l1.4 1.4M17.6 17.6L19 19M19 5l-1.4 1.4M6.4 17.6L5 19"/>',
    "gear": '<circle cx="12" cy="12" r="3"/>'
            '<path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1'
            'a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1'
            'a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1'
            'a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1'
            'a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1'
            'a1.7 1.7 0 0 0 1.9.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1'
            'a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1'
            'a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1'
            'a1.7 1.7 0 0 0-1.5 1z"/>',
    "film": '<rect x="3" y="4" width="18" height="16" rx="2"/>'
            '<path d="M7.5 4v16M16.5 4v16M3 9h4.5M3 15h4.5M16.5 9H21M16.5 15H21"/>',
    "gamepad": '<rect x="2.5" y="7.5" width="19" height="10" rx="5"/>'
               '<path d="M7 12.5h4M9 10.5v4"/>'
               '<circle cx="15.2" cy="11.2" r="1" fill="currentColor" stroke="none"/>'
               '<circle cx="17.8" cy="13.6" r="1" fill="currentColor" stroke="none"/>',
    "briefcase": '<rect x="3" y="7" width="18" height="13" rx="2"/>'
                 '<path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 12.5h18"/>',
    "user": '<circle cx="12" cy="8" r="3.6"/><path d="M4.5 20.5c0-4 3.5-6 7.5-6s7.5 2 7.5 6"/>',
    "moon": '<path d="M20.8 13.2A8.5 8.5 0 1 1 10.8 3.2a6.8 6.8 0 0 0 10 10z"/>',
    "trash": '<path d="M4 6h16M9 6V4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5V6'
             'M18.5 6l-1 13a2 2 0 0 1-2 1.8h-7a2 2 0 0 1-2-1.8l-1-13M10 10.5v6M14 10.5v6"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>'
            '<path d="M17 21v-8H7v8M7 3v4h8"/>',
    "refresh": '<path d="M22 4v6h-6"/><path d="M20.5 15a8.5 8.5 0 1 1-2-8.5L22 10"/>',
    "wand": '<path d="M6 3v4M4 5h4M17.5 14.5v4M15.5 16.5h4M19 3l-1 2M20 8l2-1M18.5 18.5'
            'M14.2 6.8 3 18l3 3L17.2 9.8z"/>',
    "play": '<path d="M7 4.5v15l12-7.5z"/>',
    "plug": '<path d="M9 3v5M15 3v5"/>'
            '<path d="M6.5 8h11v3.5a5.5 5.5 0 0 1-11 0z"/><path d="M12 17v4"/>',
    "flash": '<path d="M13 2 4.5 13.5H11L9.5 22 18 10.5h-6.5z"/>',
}


def icon(name: str, color: str = "#8a8f98", selected_color: str = "#6c8cff") -> QIcon:
    """QIcon из встроенного SVG: обычное состояние + выделенное (акцент)."""
    result = QIcon()
    result.addPixmap(_render(name, color), QIcon.Mode.Normal)
    result.addPixmap(_render(name, selected_color), QIcon.Mode.Selected)
    return result


def _render(name: str, color: str, size: int = 40) -> QPixmap:
    svg = _WRAP.format(body=_BODIES[name]).replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm
