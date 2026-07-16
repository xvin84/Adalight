"""Раскладка светодиодов по периметру экрана и расчёт зон захвата."""

from __future__ import annotations

from .config import Config

# (сторона, нормированный x, нормированный y) для каждого диода
LedPoint = tuple[str, float, float]
# (y1, y2, x1, x2) — пиксельная зона захвата
Slice = tuple[int, int, int, int]


class LedGeometry:
    CORNERS = {"TL": (0.0, 0.0), "TR": (1.0, 0.0), "BR": (1.0, 1.0), "BL": (0.0, 1.0)}
    SIDE_ENDS = {
        "top": ("TL", "TR"),
        "right": ("TR", "BR"),
        "bottom": ("BR", "BL"),
        "left": ("BL", "TL"),
    }

    WALK_PATTERNS = {
        ("top-left", "cw"): [("top", True), ("right", True), ("bottom", True), ("left", True)],
        ("top-right", "cw"): [("right", True), ("bottom", True), ("left", True), ("top", True)],
        ("bottom-right", "cw"): [("bottom", True), ("left", True), ("top", True), ("right", True)],
        ("bottom-left", "cw"): [("left", True), ("top", True), ("right", True), ("bottom", True)],
        ("top-left", "ccw"):
            [("left", False), ("bottom", False), ("right", False), ("top", False)],
        ("top-right", "ccw"):
            [("top", False), ("left", False), ("bottom", False), ("right", False)],
        ("bottom-right", "ccw"):
            [("right", False), ("top", False), ("left", False), ("bottom", False)],
        ("bottom-left", "ccw"):
            [("bottom", False), ("right", False), ("top", False), ("left", False)],
    }

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.side_counts = {
            "top": cfg.leds_top,
            "right": cfg.leds_right,
            "bottom": cfg.leds_bottom,
            "left": cfg.leds_left,
        }
        self.points: list[LedPoint] = self._build_map()

    def _build_map(self) -> list[LedPoint]:
        key = (self.cfg.start_corner, self.cfg.direction)
        if key not in self.WALK_PATTERNS:
            raise ValueError(f"Неверные start_corner/direction: {key}")

        leds: list[LedPoint] = []
        for side, forward in self.WALK_PATTERNS[key]:
            n = self.side_counts[side]
            a, b = self.SIDE_ENDS[side]
            if not forward:
                a, b = b, a
            ax, ay = self.CORNERS[a]
            bx, by = self.CORNERS[b]
            for k in range(n):
                t = (k + 0.5) / n
                leds.append((side, ax + t * (bx - ax), ay + t * (by - ay)))

        if self.cfg.flip_x:
            sw = {"left": "right", "right": "left", "top": "top", "bottom": "bottom"}
            leds = [(sw[s], 1.0 - x, y) for (s, x, y) in leds]
        if self.cfg.flip_y:
            sw = {"top": "bottom", "bottom": "top", "left": "left", "right": "right"}
            leds = [(sw[s], x, 1.0 - y) for (s, x, y) in leds]

        return leds

    def calculate_slices(self, width: int, height: int) -> list[Slice]:
        """Предрасчёт пиксельных зон захвата для каждого диода под размер кадра."""
        bw = max(1, int(width * self.cfg.band_size))
        bh = max(1, int(height * self.cfg.band_size))
        hwin = max(1, int(width * self.cfg.window_size / 2))
        vwin = max(1, int(height * self.cfg.window_size / 2))

        slices: list[Slice] = []
        for side, x, y in self.points:
            if side == "top":
                xc = int(x * width)
                y1, y2 = 0, bh
                x1, x2 = max(xc - hwin, 0), min(xc + hwin, width)
            elif side == "bottom":
                xc = int(x * width)
                y1, y2 = height - bh, height
                x1, x2 = max(xc - hwin, 0), min(xc + hwin, width)
            elif side == "left":
                yc = int(y * height)
                y1, y2 = max(yc - vwin, 0), min(yc + vwin, height)
                x1, x2 = 0, bw
            else:  # right
                yc = int(y * height)
                y1, y2 = max(yc - vwin, 0), min(yc + vwin, height)
                x1, x2 = width - bw, width

            x1, x2 = min(x1, width - 1), max(x2, 1)
            y1, y2 = min(y1, height - 1), max(y2, 1)
            slices.append((y1, y2, x1, x2))

        return slices
