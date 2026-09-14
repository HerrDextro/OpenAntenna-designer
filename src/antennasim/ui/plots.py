"""Sweep and pattern plots (pyqtgraph)."""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..analysis import pattern as pattern_analysis
from ..engine import Simulation

pg.setConfigOptions(antialias=True, background="w", foreground="#303030")

BLUE, ORANGE, GREEN, GREY = "#1f77b4", "#ff7f0e", "#2ca02c", "#8c8c8c"


def _pen(color, width=2, style=Qt.PenStyle.SolidLine):
    return pg.mkPen(color=color, width=width, style=style)


class SweepPlots(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.swr_plot = pg.PlotWidget()
        self.swr_plot.setLabel("left", "SWR")
        self.swr_plot.setLabel("bottom", "Frequency", units="MHz")
        self.swr_plot.showGrid(x=True, y=True, alpha=0.25)
        self.swr_plot.addLegend(offset=(-10, 10))
        self.z_plot = pg.PlotWidget()
        self.z_plot.setLabel("left", "Impedance", units="Ω")
        self.z_plot.setLabel("bottom", "Frequency", units="MHz")
        self.z_plot.showGrid(x=True, y=True, alpha=0.25)
        self.z_plot.addLegend(offset=(-10, 10))
        self.z_plot.setXLink(self.swr_plot)
        layout.addWidget(self.swr_plot, 1)
        layout.addWidget(self.z_plot, 1)
        self.message = QLabel("Run the simulation to see SWR and impedance.")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message)

    def show_simulation(self, sim: Simulation | None, threshold: float = 2.0):
        self.swr_plot.clear()
        self.z_plot.clear()
        if sim is None:
            self.message.show()
            return
        self.message.hide()
        f = sim.freqs
        clip = lambda s: np.minimum(s, 10.0)  # noqa: E731
        self.swr_plot.plot(f, clip(sim.swr_feedpoint), pen=_pen(BLUE), name="At feed point")
        if not np.allclose(sim.swr_rig, sim.swr_feedpoint):
            self.swr_plot.plot(f, clip(sim.swr_rig), pen=_pen(ORANGE), name="At radio")
        self.swr_plot.addItem(pg.InfiniteLine(threshold, angle=0, pen=_pen(GREY, 1, Qt.PenStyle.DashLine)))
        self.swr_plot.addItem(pg.InfiniteLine(sim.summary.design_mhz, angle=90,
                                              pen=_pen("#d62728", 1, Qt.PenStyle.DashLine)))
        self.swr_plot.setYRange(1, min(max(float(np.max(clip(sim.swr_rig))), threshold) * 1.05, 10.5))

        z = sim.z_antenna
        self.z_plot.plot(f, z.real, pen=_pen(BLUE), name="R")
        self.z_plot.plot(f, z.imag, pen=_pen(ORANGE), name="X")
        self.z_plot.plot(f, np.abs(z), pen=_pen(GREEN, 1.5, Qt.PenStyle.DashLine), name="|Z|")
        self.z_plot.addItem(pg.InfiniteLine(0, angle=0, pen=_pen(GREY, 1)))
        self.z_plot.addItem(pg.InfiniteLine(sim.summary.design_mhz, angle=90,
                                            pen=_pen("#d62728", 1, Qt.PenStyle.DashLine)))


class PolarPlot(pg.PlotWidget):
    """Polar gain plot using a linear dB scale over `range_db` below the maximum."""

    def __init__(self, title: str, half: bool, range_db: float = 30.0, parent=None):
        super().__init__(parent)
        self.half = half
        self.range_db = range_db
        self.setAspectLocked(True)
        self.hideAxis("left")
        self.hideAxis("bottom")
        self.setMouseEnabled(False, False)
        self.hideButtons()
        self.base_title = title
        self.setTitle(title)

    def _xy(self, angles_deg, gains, g_ref):
        r = np.clip((np.asarray(gains) - g_ref) / self.range_db + 1.0, 0.0, None)
        a = np.radians(angles_deg)
        return r * np.cos(a), r * np.sin(a)

    def show_cut(self, angles_deg, gains, g_ref: float, label: str):
        self.clear()
        a_max = 180 if self.half else 360
        ring_angles = np.linspace(0, a_max, 181)
        label_angle = math.radians(75)
        for level in (0, -3, -10, -20, -30):
            if -level > self.range_db:
                continue
            r = 1 + level / self.range_db
            x, y = r * np.cos(np.radians(ring_angles)), r * np.sin(np.radians(ring_angles))
            style = Qt.PenStyle.DashLine if level == -3 else Qt.PenStyle.SolidLine
            self.plot(x, y, pen=_pen("#d0d0d0", 1, style))
            if level == -3:
                continue
            t = pg.TextItem(f"{level} dB" if level else f"{g_ref:.1f} dBi", color="#808080",
                            anchor=(0.0, 1.0))
            t.setPos(r * math.cos(label_angle), r * math.sin(label_angle))
            self.addItem(t)
        for ang in range(0, a_max + (1 if self.half else 0), 30):
            c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            self.plot([0, c], [0, s], pen=_pen("#e0e0e0", 1))
            t = pg.TextItem(f"{ang}°", color="#808080", anchor=(0.5, 0.5))
            t.setPos(1.12 * c, 1.12 * s)
            self.addItem(t)
        if self.half:
            self.plot([-1.05, 1.05], [0, 0], pen=_pen("#8b6f47", 2))
        x, y = self._xy(angles_deg, gains, g_ref)
        self.plot(x, y, pen=_pen(BLUE, 2.5))
        self.setXRange(-1.25, 1.25, padding=0)
        self.setYRange(-0.1 if self.half else -1.25, 1.25, padding=0)
        self.setTitle(f"{self.base_title}<br><span style='font-size:9pt;color:#606060'>{label}</span>")


class PatternPlots(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.elevation = PolarPlot("Elevation pattern", half=True)
        self.azimuth = PolarPlot("Azimuth pattern", half=False)
        row.addWidget(self.elevation, 1)
        row.addWidget(self.azimuth, 1)
        layout.addLayout(row, 1)
        self.message = QLabel("Run the simulation to see the radiation pattern.")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message)

    def show_simulation(self, sim: Simulation | None):
        if sim is None:
            self.elevation.clear()
            self.azimuth.clear()
            self.message.show()
            return
        self.message.hide()
        p, s = sim.pattern, sim.summary
        free_space = p.theta_deg[-1] > 90
        self.elevation.half = not free_space
        angles, gains = pattern_analysis.elevation_cut(p, s.max_azimuth_deg)
        self.elevation.show_cut(angles, gains, s.max_gain_dbi,
                                f"Azimuth {s.max_azimuth_deg:.0f}°, take-off {s.takeoff_deg:.1f}°")
        az, g_az = pattern_analysis.azimuth_cut(p, max(s.takeoff_deg, 0.0))
        self.azimuth.show_cut(az, g_az, s.max_gain_dbi, f"Elevation {s.takeoff_deg:.0f}°")
