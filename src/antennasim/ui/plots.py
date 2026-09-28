"""Sweep and pattern plots (pyqtgraph)."""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from ..analysis import pattern as pattern_analysis
from ..engine import Simulation

pg.setConfigOptions(antialias=True, background="w", foreground="#303030")

BLUE, ORANGE, GREEN, GREY = "#1f77b4", "#ff7f0e", "#2ca02c", "#8c8c8c"
SWR_CEILING = 50.0  # SWR above this is "hopeless" either way; keeps the axis readable


def _pen(color, width=2, style=Qt.PenStyle.SolidLine):
    return pg.mkPen(color=color, width=width, style=style)


def _ring_levels(range_db: float) -> list[float]:
    """Ring levels for a polar plot covering `range_db` below the maximum."""
    if range_db >= 25:
        return [0, -3, -10, -20, -30]
    if range_db >= 8:
        return [0, -3, -6, -10, -20]
    step = round(range_db / 3, 1)
    return [0, -step, -2 * step, -3 * step]


def _azimuth_range_db(gains, extra, floor: float = 2.0, ceiling: float = 30.0) -> float:
    """Scale the azimuth plot to the pattern's own variation.

    A vertical with three or four radials varies by a fraction of a dB. On a
    fixed 30 dB scale that is a perfect circle, which hides the very asymmetry
    someone is looking for.
    """
    spans = [float(np.max(g) - np.min(g)) for g in [gains] + [e[1] for e in extra]]
    return min(max(max(spans) * 1.6, floor), ceiling)


def _swr_axis_top(sim, references, threshold: float) -> float:
    """Top of the SWR axis.

    Zooming in on the dip matters more than showing how bad a mismatch gets, so
    a badly matched sweep runs off the top of the axis instead of flattening the
    whole curve against it. If even the best SWR is high, fall back to fitting
    the data so the curve stays on screen.
    """
    curves = [sim.swr_rig, sim.swr_feedpoint] + [r.simulation.swr_rig for r in references]
    best = min(float(np.min(c)) for c in curves)
    peak = min(max(float(np.max(c)) for c in curves), SWR_CEILING)
    if best > 10:
        return peak * 1.05
    return max(threshold * 1.5, min(peak * 1.05, max(best * 3.0, 4.0)))


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

        header = QHBoxLayout()
        header.addStretch(1)
        self.reset_button = QPushButton("Reset zoom")
        self.reset_button.setToolTip("Fit the whole sweep again (or double-click a plot)")
        self.reset_button.clicked.connect(self.reset_zoom)
        header.addWidget(self.reset_button)
        layout.addLayout(header)
        layout.addWidget(self.swr_plot, 1)
        layout.addWidget(self.z_plot, 1)
        self.message = QLabel("Run the simulation to see SWR and impedance.")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message)

        # A zoom the user set by hand survives re-runs, so you can watch one
        # region while tweaking; a new sweep range or Reset zoom refits.
        self.user_zoomed = False
        self._fit: tuple[float, float, float] | None = None  # f_lo, f_hi, swr_max
        self._sweep: tuple[float, float] | None = None
        for plot in (self.swr_plot, self.z_plot):
            plot.getViewBox().sigRangeChangedManually.connect(self._note_manual_zoom)
            plot.scene().sigMouseClicked.connect(self._on_click)

    def _note_manual_zoom(self, *_):
        self.user_zoomed = True

    def _on_click(self, event):
        if event.double():
            self.reset_zoom()

    def reset_zoom(self):
        self.user_zoomed = False
        self._apply_fit()

    def _apply_fit(self):
        if self._fit is None:
            return
        f_lo, f_hi, swr_max = self._fit
        self.swr_plot.setXRange(f_lo, f_hi, padding=0.02)
        self.swr_plot.setYRange(1, swr_max)
        self.z_plot.setXRange(f_lo, f_hi, padding=0.02)
        self.z_plot.enableAutoRange(axis="y")

    def show_simulation(self, sim: Simulation | None, threshold: float = 2.0,
                        references: list = ()):
        self.swr_plot.clear()
        self.z_plot.clear()
        if sim is None:
            self.message.show()
            return
        self.message.hide()
        for ref in references:
            pen = _pen(ref.color, 1.5, Qt.PenStyle.DashLine)
            self.swr_plot.plot(ref.simulation.freqs, np.minimum(ref.simulation.swr_rig, SWR_CEILING),
                               pen=pen, name=f"{ref.name} (SWR)")
            self.z_plot.plot(ref.simulation.freqs, ref.simulation.z_antenna.real, pen=pen,
                             name=f"{ref.name} (R)")
            self.z_plot.plot(ref.simulation.freqs, ref.simulation.z_antenna.imag,
                             pen=_pen(ref.color, 1.5, Qt.PenStyle.DotLine),
                             name=f"{ref.name} (X)")
        f = sim.freqs
        clip = lambda s: np.minimum(s, SWR_CEILING)  # noqa: E731
        self.swr_plot.plot(f, clip(sim.swr_feedpoint), pen=_pen(BLUE), name="At feed point")
        if not np.allclose(sim.swr_rig, sim.swr_feedpoint):
            self.swr_plot.plot(f, clip(sim.swr_rig), pen=_pen(ORANGE), name="At radio")
        self.swr_plot.addItem(pg.InfiniteLine(threshold, angle=0, pen=_pen(GREY, 1, Qt.PenStyle.DashLine)))
        self.swr_plot.addItem(pg.InfiniteLine(sim.summary.design_mhz, angle=90,
                                              pen=_pen("#d62728", 1, Qt.PenStyle.DashLine)))
        f_lo = min([float(f[0])] + [float(r.simulation.freqs[0]) for r in references])
        f_hi = max([float(f[-1])] + [float(r.simulation.freqs[-1]) for r in references])
        self._fit = (f_lo, f_hi, _swr_axis_top(sim, references, threshold))
        # A new sweep range makes an old zoom meaningless, so refit then.
        if self._sweep != (float(f[0]), float(f[-1])):
            self._sweep = (float(f[0]), float(f[-1]))
            self.user_zoomed = False
        if not self.user_zoomed:
            self._apply_fit()

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

    def _fit_view(self):
        """Show the whole circle whatever shape the widget is.

        The view is aspect-locked, and pyqtgraph honours that by shrinking the
        x range in a tall, narrow widget, which clips the pattern. Ask for a
        rectangle that already matches the widget instead.
        """
        x_lo, x_hi = -1.25, 1.25
        y_lo, y_hi = (-0.1 if self.half else -1.25), 1.25

        width = max(self.width(), 1)
        height = max(self.height(), 1)
        data_w, data_h = x_hi - x_lo, y_hi - y_lo
        if width / height > data_w / data_h:
            pad = (data_h * width / height - data_w) / 2
            x_lo, x_hi = x_lo - pad, x_hi + pad
        else:
            pad = (data_w * height / width - data_h) / 2
            y_lo, y_hi = y_lo - pad, y_hi + pad
        self.setXRange(x_lo, x_hi, padding=0)
        self.setYRange(y_lo, y_hi, padding=0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # pyqtgraph resizes during its own constructor (before `half` exists) and
        # again while closing (after it drops the plot item).
        if hasattr(self, "half") and getattr(self, "plotItem", None) is not None:
            self._fit_view()

    def _xy(self, angles_deg, gains, g_ref):
        r = np.clip((np.asarray(gains) - g_ref) / self.range_db + 1.0, 0.0, None)
        a = np.radians(angles_deg)
        return r * np.cos(a), r * np.sin(a)

    def show_cut(self, angles_deg, gains, g_ref: float, label: str, extra: list = ()):
        self.clear()
        a_max = 180 if self.half else 360
        ring_angles = np.linspace(0, a_max, 181)
        label_angle = math.radians(75)
        for level in _ring_levels(self.range_db):
            r = 1 + level / self.range_db
            x, y = r * np.cos(np.radians(ring_angles)), r * np.sin(np.radians(ring_angles))
            style = Qt.PenStyle.DashLine if level == -3 else Qt.PenStyle.SolidLine
            self.plot(x, y, pen=_pen("#d0d0d0", 1, style))
            if level == -3:
                continue
            text = f"{g_ref:.1f} dBi" if not level else (
                f"{level:.1f} dB" if abs(level) < 10 else f"{level:.0f} dB")
            t = pg.TextItem(text, color="#808080", anchor=(0.0, 1.0))
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
        for ref_angles, ref_gains, color, name in extra:
            rx, ry = self._xy(ref_angles, ref_gains, g_ref)
            self.plot(rx, ry, pen=_pen(color, 1.5, Qt.PenStyle.DashLine), name=name)
        x, y = self._xy(angles_deg, gains, g_ref)
        self.plot(x, y, pen=_pen(BLUE, 2.5))
        self._fit_view()
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

    def show_simulation(self, sim: Simulation | None, references: list = ()):
        if sim is None:
            self.elevation.clear()
            self.azimuth.clear()
            self.message.show()
            return
        self.message.hide()
        p, s = sim.pattern, sim.summary
        free_space = p.theta_deg[-1] > 90
        self.elevation.half = not free_space
        # All curves share the live design's reference level so gains compare directly.
        extra_el, extra_az = [], []
        for ref in references:
            rp = ref.simulation.pattern
            extra_el.append((*pattern_analysis.elevation_cut(rp, s.max_azimuth_deg),
                             ref.color, ref.name))
            extra_az.append((*pattern_analysis.azimuth_cut(rp, max(s.takeoff_deg, 0.0)),
                             ref.color, ref.name))
        angles, gains = pattern_analysis.elevation_cut(p, s.max_azimuth_deg)
        self.elevation.show_cut(angles, gains, s.max_gain_dbi,
                                f"Azimuth {s.max_azimuth_deg:.0f}°, take-off {s.takeoff_deg:.1f}°",
                                extra_el)
        az, g_az = pattern_analysis.azimuth_cut(p, max(s.takeoff_deg, 0.0))
        self.azimuth.range_db = _azimuth_range_db(g_az, extra_az)
        spread = s.azimuth_variation_db
        shape = ("omnidirectional" if spread < 0.1 else
                 f"{spread:.1f} dB variation, max at {s.max_azimuth_deg:.0f}°")
        self.azimuth.show_cut(az, g_az, s.max_gain_dbi,
                              f"Elevation {s.takeoff_deg:.0f}°, {shape}", extra_az)
