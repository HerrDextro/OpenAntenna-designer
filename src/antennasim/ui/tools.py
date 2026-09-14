"""Tool dialogs: resonance tuner and coil calculator."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QLabel, QProgressBar, QPushButton, QVBoxLayout)

from ..analysis.coil import design_coil, reactance_ohm
from ..engine import SimulationBlocked, tune
from ..model.units import format_length
from ..solver.base import SolverBackend
from .controller import DocumentController


class _TuneSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _TuneJob(QRunnable):
    def __init__(self, project, tunable, backend, target):
        super().__init__()
        self.args = (project, tunable, backend, target)
        self.signals = _TuneSignals()

    def run(self):
        try:
            self.signals.done.emit(tune(*self.args))
        except SimulationBlocked as e:
            self.signals.failed.emit(f"Fix model errors first: {e}")
        except Exception as e:  # solver errors are shown to the user
            self.signals.failed.emit(str(e))


class TuneDialog(QDialog):
    def __init__(self, ctl: DocumentController, backend: SolverBackend, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tune to resonance")
        self.ctl, self.backend = ctl, backend
        project = ctl.project
        self.tunables = project.template.tunables(project)

        self.param = QComboBox()
        for t in self.tunables:
            self.param.addItem(t.label)
        self.target = QDoubleSpinBox()
        self.target.setDecimals(4)
        self.target.setRange(0.1, 3000)
        self.target.setSuffix(" MHz")
        self.target.setValue(project.simulation["design_mhz"])
        self.result = QLabel("Adjusts the chosen parameter until the reactance at the target "
                             "frequency is zero.")
        self.result.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()

        self.run_button = QPushButton("Tune")
        self.run_button.clicked.connect(self._run)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply
                                        | QDialogButtonBox.StandardButton.Close)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        self.buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("Parameter", self.param)
        form.addRow("Target frequency", self.target)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.run_button)
        layout.addWidget(self.progress)
        layout.addWidget(self.result)
        layout.addWidget(self.buttons)
        self._value = None
        self._job = None

    def _run(self):
        if not self.tunables:
            return
        tunable = self.tunables[self.param.currentIndex()]
        self._job = _TuneJob(self.ctl.project.clone(), tunable, self.backend, self.target.value())
        self._job.signals.done.connect(self._done)
        self._job.signals.failed.connect(self._failed)
        self.run_button.setEnabled(False)
        self.progress.show()
        self.result.setText("Tuning…")
        QThreadPool.globalInstance().start(self._job)

    def _done(self, result):
        self.progress.hide()
        self.run_button.setEnabled(True)
        tunable = self.tunables[self.param.currentIndex()]
        spec = next(s for s in self.ctl.project.node_specs(tunable.node_id) if s.key == tunable.key)
        if spec.kind in ("length", "small_length"):
            shown = format_length(result.value, self.ctl.project.units)
        else:
            shown = f"{result.value:.3f} µH" if spec.kind == "inductance" else f"{result.value:.4g}"
        status = "Resonant" if result.converged else result.message
        self.result.setText(f"{status}: {tunable.label} = {shown}\n"
                            f"Reactance {result.reactance:+.2f} Ω after {result.iterations} solves.")
        self._value = result.value if result.converged else None
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).setEnabled(result.converged)

    def _failed(self, message: str):
        self.progress.hide()
        self.run_button.setEnabled(True)
        self.result.setText(message)

    def _apply(self):
        if self._value is None:
            return
        tunable = self.tunables[self.param.currentIndex()]
        self.ctl.set_value(tunable.node_id, tunable.key, self._value)
        self.accept()


class CoilDialog(QDialog):
    def __init__(self, ctl: DocumentController, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Coil calculator")
        project = ctl.project
        coil = project.first_part("loading_coil")

        def spin(value, lo, hi, suffix, decimals=2, step=1.0):
            s = QDoubleSpinBox()
            s.setDecimals(decimals)
            s.setRange(lo, hi)
            s.setSingleStep(step)
            s.setSuffix(suffix)
            s.setValue(value)
            s.valueChanged.connect(self._update)
            return s

        self.inductance = spin(coil.params["inductance"] if coil else 10.0, 0.01, 10000, " µH", 3)
        self.q = spin(coil.params["q"] if coil else 200.0, 1, 5000, "", 0, 10)
        self.form_d = spin(50.0, 1, 1000, " mm", 1)
        self.wire_d = spin(1.5, 0.05, 20, " mm", 2, 0.1)
        self.spacing = spin(1.0, 1.0, 10, " × wire Ø", 2, 0.1)
        self.freq = spin(project.simulation["design_mhz"], 0.1, 3000, " MHz", 4, 0.1)
        self.output = QLabel()
        self.output.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Inductance", self.inductance)
        form.addRow("Coil diameter (mean)", self.form_d)
        form.addRow("Wire diameter", self.wire_d)
        form.addRow("Turn pitch", self.spacing)
        form.addRow("Frequency", self.freq)
        form.addRow("Coil Q", self.q)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.output)
        layout.addWidget(close)
        self._update()

    def _update(self, *_):
        c = design_coil(self.inductance.value(), self.form_d.value() / 1000,
                        self.wire_d.value() / 1000, self.spacing.value())
        x = reactance_ohm(self.inductance.value(), self.freq.value())
        ratio = c.coil_length_m / c.form_diameter_m if c.form_diameter_m else 0
        note = "" if ratio >= 0.4 else "\n⚠ Coil is short for its diameter; Wheeler's formula is less accurate."
        self.output.setText(
            f"<b>{c.turns:.1f} turns</b>, coil length {c.coil_length_m * 1000:.1f} mm<br>"
            f"Wire needed ≈ {c.wire_length_m:.2f} m (plus leads)<br>"
            f"Reactance {x:.1f} Ω, loss resistance ≈ {x / self.q.value():.2f} Ω at Q {self.q.value():.0f}"
            + note.replace("\n", "<br>"))
