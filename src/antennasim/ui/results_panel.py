"""Right panel (bottom): results summary, model warnings and cut list."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QGridLayout, QGroupBox, QHeaderView, QLabel,
                               QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from ..engine import Simulation
from ..geometry.validation import ERROR, INFO, WARNING
from ..model.materials import COAX
from ..model.units import format_length
from .controller import DocumentController

_LEVEL_STYLE = {ERROR: ("✖", "#c62828"), WARNING: ("⚠", "#b26a00"), INFO: ("ℹ", "#1565c0")}


def _fmt_z(z: complex) -> str:
    sign = "+" if z.imag >= 0 else "−"
    return f"{z.real:.1f} {sign} j{abs(z.imag):.1f} Ω"


class ResultsPanel(QWidget):
    def __init__(self, ctl: DocumentController, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.sim: Simulation | None = None
        self.stale = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.results_box = QGroupBox("Results")
        self.grid = QGridLayout(self.results_box)
        self.grid.setColumnStretch(1, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.results_box)

        self.bottom_tabs = QTabWidget()
        self.issues = QListWidget()
        self.issues.setWordWrap(True)
        self.issues.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.issues.itemClicked.connect(self._issue_clicked)
        self.bottom_tabs.addTab(self.issues, "Model checks")

        self.cut = QTableWidget(0, 3)
        self.cut.setHorizontalHeaderLabels(["Item", "Qty", "Length"])
        self.cut.verticalHeader().hide()
        self.cut.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.cut.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.bottom_tabs.addTab(self.cut, "Cut list")
        layout.addWidget(self.bottom_tabs, 1)

        ctl.model_changed.connect(self._model_changed)
        ctl.units_changed.connect(lambda _: self.refresh())
        self.refresh()

    def set_simulation(self, sim: Simulation | None, stale: bool = False):
        self.sim = sim
        self.stale = stale
        self.refresh()

    def set_status(self, text: str):
        self.status.setText(text)

    def _model_changed(self):
        self.stale = True
        self.refresh()

    # ---- rendering ---------------------------------------------------------

    def refresh(self):
        self._fill_results()
        self._fill_issues()
        self._fill_cut_list()

    def _row(self, r: int, label: str, value: str, tip: str = ""):
        name = QLabel(label)
        val = QLabel(value)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if tip:
            name.setToolTip(tip)
            val.setToolTip(tip)
        if self.stale:
            val.setStyleSheet("color: #999;")
        self.grid.addWidget(name, r, 0)
        self.grid.addWidget(val, r, 1)

    def _fill_results(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget() and item.widget() is not self.status:
                item.widget().deleteLater()
        if self.sim is None:
            self.grid.addWidget(QLabel("Press Run (F5) to simulate."), 0, 0, 1, 2)
            self.grid.addWidget(self.status, 1, 0, 1, 2)
            return
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
        for i, (label, value, tip) in enumerate(rows):
            self._row(i, label, value, tip)
        if self.stale:
            note = QLabel("Design changed — results are outdated.")
            note.setStyleSheet("color: #b26a00;")
            self.grid.addWidget(note, len(rows), 0, 1, 2)
        self.grid.addWidget(self.status, len(rows) + 1, 0, 1, 2)

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

    def _fill_cut_list(self):
        project = self.ctl.project
        items = project.template.cut_list(project)
        self.cut.setRowCount(len(items))
        for r, c in enumerate(items):
            length = format_length(c.length_m, project.units) if c.length_m > 0 else ""
            for col, text in enumerate((c.name + (f"  ({c.note})" if c.note else ""),
                                        str(c.quantity), length)):
                cell = QTableWidgetItem(text)
                if col:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.cut.setItem(r, col, cell)
