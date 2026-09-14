"""Lightweight 3D orbit view drawn with QPainter (no OpenGL dependency).

Shows the wire model coloured by current magnitude and the radiation pattern
as a wireframe surface.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..engine import Simulation
from ..geometry.wire_model import WireModel


def _current_color(t: float) -> QColor:
    """Blue (low) -> green -> red (high)."""
    t = min(max(t, 0.0), 1.0)
    if t < 0.5:
        u = t / 0.5
        return QColor(int(40 + 20 * u), int(90 + 130 * u), int(220 - 140 * u))
    u = (t - 0.5) / 0.5
    return QColor(int(60 + 180 * u), int(220 - 170 * u), int(80 - 40 * u))


class View3D(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.yaw = math.radians(35)
        self.pitch = math.radians(20)
        self.zoom = 1.0
        self._last = None
        self.model: WireModel | None = None
        self.sim: Simulation | None = None
        self.show_pattern = True

    def set_model(self, model: WireModel):
        self.model = model
        self.update()

    def set_simulation(self, sim: Simulation | None):
        self.sim = sim
        self.update()

    # ---- projection ------------------------------------------------------

    def _rotate(self, pts: np.ndarray) -> np.ndarray:
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        x, y, z = pts[..., 0], pts[..., 1], pts[..., 2]
        # Yaw around z, then tilt the camera down by `pitch`. y1 points into the
        # screen, so from above, farther points appear higher.
        x1 = cy * x - sy * y
        y1 = sy * x + cy * y
        sx = x1
        sz = cp * z + sp * y1
        depth = -sp * z + cp * y1
        return np.stack([sx, sz, depth], axis=-1)

    def _scene(self):
        lo, hi = self.model.bounds()
        center = np.array([(lo[i] + hi[i]) / 2 for i in range(3)])
        size = max(max(hi[i] - lo[i] for i in range(3)), 0.5)
        scale = min(self.width(), self.height()) / (size * 1.8) * self.zoom
        return center, size, scale

    def _to_screen(self, pts: np.ndarray, center, scale) -> np.ndarray:
        r = self._rotate(pts - center)
        return np.stack([self.width() / 2 + r[..., 0] * scale,
                         self.height() / 2 - r[..., 1] * scale], axis=-1)

    # ---- painting --------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#fbfbfd"))
        if self.model is None or not self.model.wires:
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No model")
            return
        center, size, scale = self._scene()

        if self.model.ground.kind != "free_space":
            self._draw_ground(p, center, size, scale)
        if self.sim is not None and self.show_pattern:
            self._draw_pattern(p, center, size, scale)
        self._draw_wires(p, center, scale)

        p.setPen(QColor("#505050"))
        p.drawText(10, 20, "3D view — drag to rotate, wheel to zoom")
        if self.sim is not None:
            p.drawText(10, 38, "Wire colour: current magnitude (blue low, red high)")
        self._draw_axes(p)

    def _draw_ground(self, p: QPainter, center, size, scale):
        extent = size * 1.2
        step = extent / 6
        pen = QPen(QColor(139, 111, 71, 90), 1)
        p.setPen(pen)
        cx, cy = center[0], center[1]
        for i in range(-6, 7):
            a = np.array([[cx + i * step, cy - extent, 0.0], [cx + i * step, cy + extent, 0.0]])
            b = np.array([[cx - extent, cy + i * step, 0.0], [cx + extent, cy + i * step, 0.0]])
            for line in (a, b):
                s = self._to_screen(line, center, scale)
                p.drawLine(QPointF(*s[0]), QPointF(*s[1]))

    def _draw_pattern(self, p: QPainter, center, size, scale):
        pat = self.sim.pattern
        g = pat.gain_total_dbi
        r = np.clip((g - g.max()) / 30.0 + 1.0, 0.0, None) * size * 0.9
        th = np.radians(pat.theta_deg)[:, None]
        ph = np.radians(pat.phi_deg)[None, :]
        src = self.model.wires[self.model.source.wire].p1 if self.model.source else center
        pts = np.stack([r * np.sin(th) * np.cos(ph) + src[0],
                        r * np.sin(th) * np.sin(ph) + src[1],
                        r * np.cos(th) + src[2]], axis=-1)
        screen = self._to_screen(pts, center, scale)
        p.setPen(QPen(QColor(31, 119, 180, 70), 1))
        n_t, n_p = screen.shape[:2]
        for i in range(0, n_t, max(n_t // 15, 1)):
            for j in range(n_p - 1):
                p.drawLine(QPointF(*screen[i, j]), QPointF(*screen[i, j + 1]))
        for j in range(0, n_p, max(n_p // 24, 1)):
            for i in range(n_t - 1):
                p.drawLine(QPointF(*screen[i, j]), QPointF(*screen[i + 1, j]))

    def _draw_wires(self, p: QPainter, center, scale):
        currents = None
        if self.sim is not None and self.sim.result.design.currents is not None:
            mags = np.abs(self.sim.result.design.currents)
            if len(mags) == sum(max(w.segments, 1) for w in self.model.wires):
                currents = mags / max(mags.max(), 1e-30)
        k = 0
        segs = []
        for wi, w in enumerate(self.model.wires):
            for a, b in self.model.segment_endpoints(wi):
                t = currents[k] if currents is not None else None
                segs.append((np.array([a, b]), t))
                k += 1
        pts = np.array([s[0] for s in segs])
        screen = self._to_screen(pts, center, scale)
        depth = self._rotate(pts - center)[..., 2].mean(axis=1)
        for idx in np.argsort(-depth):
            t = segs[idx][1]
            color = _current_color(t) if t is not None else QColor("#1f4e8c")
            pen = QPen(color, 3.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(*screen[idx, 0]), QPointF(*screen[idx, 1]))

    def _draw_axes(self, p: QPainter):
        origin = np.array([55.0, self.height() - 45.0])
        for vec, name, color in (((1, 0, 0), "x", "#d62728"), ((0, 1, 0), "y", "#2ca02c"),
                                 ((0, 0, 1), "z", "#1f77b4")):
            r = self._rotate(np.array(vec, dtype=float))
            end = origin + np.array([r[0], -r[1]]) * 28
            p.setPen(QPen(QColor(color), 2))
            p.drawLine(QPointF(*origin), QPointF(*end))
            p.drawText(QPointF(end[0] + 3, end[1] + 3), name)

    # ---- interaction -----------------------------------------------------

    def mousePressEvent(self, event):
        self._last = event.position()

    def mouseMoveEvent(self, event):
        if self._last is None:
            return
        d = event.position() - self._last
        self._last = event.position()
        self.yaw += d.x() * 0.01
        self.pitch = min(max(self.pitch + d.y() * 0.01, -math.pi / 2), math.pi / 2)
        self.update()

    def mouseReleaseEvent(self, event):
        self._last = None

    def wheelEvent(self, event):
        self.zoom *= 1.15 ** (event.angleDelta().y() / 120)
        self.update()
