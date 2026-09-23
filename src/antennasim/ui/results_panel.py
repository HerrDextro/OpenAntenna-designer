"""Right panel (bottom): results summary, model warnings and cut list."""

from __future__ import annotations

import re

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
                               QTabWidget, QVBoxLayout, QWidget)

from ..engine import Simulation
from ..geometry.validation import ERROR, INFO, WARNING
from ..model.materials import COAX
from ..model.units import format_length
from .controller import DocumentController
from .formatting import results_text

_LEVEL_STYLE = {ERROR: ("✖", "#c62828"), WARNING: ("⚠", "#b26a00"), INFO: ("ℹ", "#1565c0")}

CHANGED_COLOR = "#0b6bcb"
BASELINE_COLOR = "#7b5cd6"
HIGHLIGHT_MS = 6000


def _fmt_z(z: complex) -> str:
    sign = "+" if z.imag >= 0 else "−"
    return f"{z.real:.1f} {sign} j{abs(z.imag):.1f} Ω"


class ResultsPanel(QWidget):
    def __init__(self, ctl: DocumentController, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.sim: Simulation | None = None
        self.stale = True
        self.busy = False
        self.changed: dict[str, str] = {}  # label -> previous value
        self.baseline = None  # compare.Reference, when comparing
        self._last_values: dict[str, str] = {}
        self._highlight_timer = QTimer(self, singleShot=True)
        self._highlight_timer.timeout.connect(self._clear_highlight)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.results_box = QGroupBox("Results")
        box_layout = QVBoxLayout(self.results_box)
        grid_host = QWidget()
        self.grid = QGridLayout(grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setColumnStretch(1, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        box_layout.addWidget(grid_host)
        copy_row = QHBoxLayout()
        copy_row.addStretch(1)
        self.copy_button = QPushButton("Copy results")
        self.copy_button.setToolTip("Copy these numbers as text for your notes")
        self.copy_button.clicked.connect(self._copy_results)
        copy_row.addWidget(self.copy_button)
        box_layout.addLayout(copy_row)
        # Scrolled so rows keep their height instead of overlapping when the
        # panel is short.
        scroll = QScrollArea()
        scroll.setWidget(self.results_box)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setMinimumHeight(220)
        layout.addWidget(scroll, 3)

        self.bottom_tabs = QTabWidget()
        self.issues = QListWidget()
        self.issues.setWordWrap(True)
        self.issues.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.issues.itemClicked.connect(self._issue_clicked)
        self.bottom_tabs.addTab(self.issues, "Model checks")

        layout.addWidget(self.bottom_tabs, 2)

        ctl.model_changed.connect(self._model_changed)
        ctl.units_changed.connect(lambda _: self.refresh())
        self.refresh()

    def set_baseline(self, reference):
        """Reference whose values the results are compared against (or None)."""
        self.baseline = reference
        self.refresh()

    def _copy_results(self):
        QGuiApplication.clipboard().setText(
            results_text(self.ctl.project, self._summary_rows()))

    def set_simulation(self, sim: Simulation | None, stale: bool = False):
        self.sim = sim
        self.stale = stale
        self.busy = False
        if sim is not None and not stale:
            # Remember which values moved since the last completed run. A repeat
            # run with identical numbers keeps the previous highlight rather than
            # clearing it, so re-running doesn't hide what just changed.
            new = {label: value for label, value, _ in self._summary_rows()}
            moved = {k: v for k, v in self._last_values.items() if k in new and new[k] != v}
            self._last_values = new
            if moved:
                self.changed = moved
                self._highlight_timer.start(HIGHLIGHT_MS)
        self.refresh()

    def set_status(self, text: str, error: bool = False):
        self.status.setText(text)
        self.status.setStyleSheet("color: #c62828; font-weight: 600;" if error and text else "")

    def set_busy(self, busy: bool):
        self.busy = busy
        if busy:
            self.changed = {}
        self.refresh()

    def _clear_highlight(self):
        self.changed = {}
        self.refresh()

    def _model_changed(self):
        self.stale = True
        self.refresh()

    # ---- rendering ---------------------------------------------------------

    def refresh(self):
        self._fill_results()
        self._fill_issues()

    def _row(self, r: int, label: str, value: str, tip: str = ""):
        name = QLabel(label)
        val = QLabel(value)
        if self.baseline is not None and not self.stale and not self.busy:
            was = self.baseline.summary_rows.get(label)
            delta = _delta_text(was, value)
            if delta:
                cell = QLabel(delta)
                cell.setStyleSheet(f"color: {BASELINE_COLOR};")
                cell.setToolTip(f"{self.baseline.name}: {was}")
                cell.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                self.grid.addWidget(cell, r, 2)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if tip:
            name.setToolTip(tip)
            val.setToolTip(tip)
        if self.stale or self.busy:
            val.setStyleSheet("color: #999;")
        elif label in self.changed:
            val.setStyleSheet(f"color: {CHANGED_COLOR}; font-weight: 600;")
            was = f"changed, was {self.changed[label]}"
            val.setToolTip(f"{tip}\n{was}" if tip else was)
            name.setStyleSheet(f"color: {CHANGED_COLOR};")
        self.grid.addWidget(name, r, 0)
        self.grid.addWidget(val, r, 1)

    def _fill_results(self):
        while self.grid.count():
            widget = self.grid.takeAt(0).widget()
            if widget is None or widget is self.status:
                continue
            # Unparent as well as delete: deleteLater() alone leaves the old row
            # painted on top of the new one until the event loop catches up.
            widget.setParent(None)
            widget.deleteLater()
        rows = self._summary_rows()
        if not rows:
            self.grid.addWidget(QLabel("Press Run (F5) to simulate."), 0, 0, 1, 3)
            self.grid.addWidget(self.status, 1, 0, 1, 3)
            return
        note = ""
        if self.busy:
            note, color = "Simulating…", "#1565c0"
        elif self.stale:
            note, color = "Design changed — results are outdated. Press Run (F5).", "#b26a00"
        elif self.changed:
            note, color = f"{len(self.changed)} value(s) changed in this run.", CHANGED_COLOR
        offset = 0
        if note:
            banner = QLabel(note)
            banner.setStyleSheet(f"color: {color};")
            banner.setWordWrap(True)
            self.grid.addWidget(banner, 0, 0, 1, 3)
            offset = 1
        for i, (label, value, tip) in enumerate(rows):
            self._row(i + offset, label, value, tip)
        self.grid.addWidget(self.status, len(rows) + offset, 0, 1, 3)

    def _summary_rows(self) -> list[tuple[str, str, str]]:
        if self.sim is None:
            return []
        s = self.sim.summary
        fl = self.ctl.project.feedline
        units = self.ctl.project.units
        rows = [
            ("Design frequency", f"{s.design_mhz:.4f} MHz", ""),
            ("Impedance (antenna)", _fmt_z(s.z_antenna), "Feed-point impedance from NEC2"),
        ]
        if fl["transformer_ratio"] != 1.0:
            rows.append((f"After {fl['transformer_ratio']:g}:1", _fmt_z(s.z_feedpoint), ""))
        rows.append(("SWR at feed point", f"{s.swr_feedpoint:.2f}", f"Relative to {fl['z0']:g} Ω"))
        if fl["coax"] != "none" and fl["length"] > 0:
            coax = COAX[fl["coax"]].label
            rows.append(("SWR at radio", f"{s.swr_rig:.2f}",
                         f"After {format_length(fl['length'], units, 1)} of {coax}"))
            rows.append(("Feedline loss", f"{s.feedline_loss_db:.2f} dB", "Including mismatch loss"))
        res = ", ".join(f"{f:.3f}" for f in s.resonances_mhz) or "none in sweep"
        rows.append(("Resonance (X = 0)", f"{res} MHz" if s.resonances_mhz else res, ""))
        rows.append(("Minimum SWR", f"{s.min_swr:.2f} @ {s.min_swr_mhz:.3f} MHz", "At the radio"))
        thr = self.ctl.project.simulation["swr_threshold"]
        if s.bandwidth_mhz:
            lo, hi = s.bandwidth_mhz
            f0, f1 = self.sim.freqs[0], self.sim.freqs[-1]
            edge = " (sweep edge)" if lo <= f0 + 1e-9 or hi >= f1 - 1e-9 else ""
            rows.append((f"SWR ≤ {thr:g} band", f"{lo:.3f} – {hi:.3f} MHz{edge}",
                         f"Width {(hi - lo) * 1000:.0f} kHz"))
        else:
            rows.append((f"SWR ≤ {thr:g} band", "none", ""))
        rows.append(("Max gain", f"{s.max_gain_dbi:.2f} dBi", ""))
        rows.append(("Take-off angle", f"{s.takeoff_deg:.1f}°", "Elevation of maximum gain"))
        if s.elevation_beamwidth_deg:
            rows.append(("Elevation −3 dB width", f"{s.elevation_beamwidth_deg:.0f}°", ""))
        if s.efficiency is not None:
            rows.append(("Efficiency", f"{s.efficiency * 100:.1f} %",
                         "Radiated / input power: conductor, coil and ground-loss "
                         "resistance. Ground reflection loss shows in gain instead."))
        if s.ground_loss_ohm is not None:
            rows.append(("Ground loss", f"{s.ground_loss_ohm:.1f} Ω", "Series loss resistance"))
        rows.append(("Model", f"{s.wires} wires, {s.segments} segments", ""))
        return rows

    def _fill_issues(self):
        self.issues.clear()
        issues = self.ctl.built.issues
        problems = sum(1 for i in issues if i.level in (ERROR, WARNING))
        self.bottom_tabs.setTabText(0, f"Model checks ({problems})" if problems else "Model checks")
        if not issues:
            item = QListWidgetItem("✔ No problems found")
            item.setForeground(QColor("#2e7d32"))
            self.issues.addItem(item)
            return
        order = {ERROR: 0, WARNING: 1, INFO: 2}
        for issue in sorted(issues, key=lambda i: order[i.level]):
            icon, color = _LEVEL_STYLE[issue.level]
            item = QListWidgetItem(f"{icon} {issue.message}")
            item.setForeground(QColor(color))
            item.setData(Qt.ItemDataRole.UserRole, issue.node_id)
            self.issues.addItem(item)

    def _issue_clicked(self, item: QListWidgetItem):
        node = item.data(Qt.ItemDataRole.UserRole)
        if node:
            self.ctl.select(node)


def _first_number(text: str) -> float | None:
    match = re.search(r"[-+]?\d*\.?\d+", text.replace("−", "-"))
    return float(match.group()) if match else None


def _delta_text(was: str | None, now: str) -> str:
    """Signed difference of the leading number, e.g. "(+0.12)"."""
    if not was or was == now:
        return ""
    a, b = _first_number(was), _first_number(now)
    if a is None or b is None:
        return "(was " + was + ")"
    diff = b - a
    if abs(diff) < 5e-4:
        return ""
    digits = 3 if abs(diff) < 1 else 2
    return f"({diff:+.{digits}f})"
