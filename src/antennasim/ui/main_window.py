"""Main window: toolbar on top, part tree left, diagram/plots centre, info right."""

from __future__ import annotations

import itertools
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QDockWidget, QDoubleSpinBox, QFileDialog, QLabel,
                               QMainWindow, QMenu, QMessageBox, QSplitter, QTabWidget,
                               QToolBar, QToolButton, QWidget)

from ..engine import SimulationBlocked, simulate
from ..fileio.nec_export import export_nec
from ..fileio.project_file import EXTENSION, load_project, save_project
from ..model.document import NODE_SIMULATION, Project
from ..model.parts import PART_TYPES
from ..model.units import IMPERIAL, METRIC
from ..solver.nec2_backend import Nec2Backend
from ..templates import all_templates
from ..templates.base import SIDE, TOP
from .controller import DocumentController
from .diagram import DiagramView
from .part_tree import PartTree
from .plots import PatternPlots, SweepPlots
from .properties_panel import PropertiesPanel
from .results_panel import ResultsPanel
from .tools import CoilDialog, TuneDialog
from .view3d import View3D

FILE_FILTER = f"AntennaSim project (*{EXTENSION})"


class _SimSignals(QObject):
    done = Signal(int, object)
    failed = Signal(int, str)


class _SimJob(QRunnable):
    def __init__(self, generation: int, project: Project, backend):
        super().__init__()
        self.generation, self.project, self.backend = generation, project, backend
        self.signals = _SimSignals()

    def run(self):
        try:
            self.signals.done.emit(self.generation, simulate(self.project, self.backend))
        except SimulationBlocked as e:
            self.signals.failed.emit(self.generation, f"Cannot simulate: {e}")
        except Exception as e:  # show solver problems in the UI instead of crashing
            self.signals.failed.emit(self.generation, str(e))


class MainWindow(QMainWindow):
    def __init__(self, project: Project | None = None):
        super().__init__()
        self.backend = Nec2Backend()
        self.ctl = DocumentController(project or Project.new("monopole"), self)
        self.path: Path | None = None
        self.sim = None
        self._generation = itertools.count(1)
        self._latest = 0
        self._running = False
        self._rerun = False
        self.settings = QSettings("AntennaSim", "AntennaSim")

        self._build_central()
        self._build_docks()
        self._build_actions()
        self._build_toolbar_and_menus()

        self.auto_timer = QTimer(self, singleShot=True, interval=400)
        self.auto_timer.timeout.connect(self.run_simulation)
        self.ctl.model_changed.connect(self._on_model_changed)
        self.ctl.value_changed.connect(self._on_value_changed)
        self.ctl.selection_changed.connect(lambda _: self._update_part_actions())
        self.ctl.undo_stack.cleanChanged.connect(lambda _: self._update_title())
        self.ctl.units_changed.connect(self._sync_units_actions)

        self.statusBar().showMessage(f"Solver: {self.backend.name}"
                                     if self.backend.executable else
                                     "nec2c not found — build it with third_party/build_nec2c.py")
        self.resize(1500, 900)
        self._update_title()
        self._refresh_views()
        QTimer.singleShot(0, self.run_simulation)

    # ---- layout -------------------------------------------------------------

    def _build_central(self):
        self.tabs = QTabWidget()
        split = QSplitter(Qt.Orientation.Horizontal)
        self.side_view = DiagramView(self.ctl, SIDE)
        self.top_view = DiagramView(self.ctl, TOP)
        split.addWidget(self.side_view)
        split.addWidget(self.top_view)
        split.setSizes([700, 350])
        self.tabs.addTab(split, "Diagram")
        self.sweep_plots = SweepPlots()
        self.tabs.addTab(self.sweep_plots, "SWR && impedance")
        self.pattern_plots = PatternPlots()
        self.tabs.addTab(self.pattern_plots, "Pattern")
        self.view3d = View3D()
        self.tabs.addTab(self.view3d, "3D")
        self.setCentralWidget(self.tabs)

    def _build_docks(self):
        self.tree = PartTree(self.ctl)
        left = QDockWidget("Parts", self)
        left.setObjectName("parts")
        left.setWidget(self.tree)
        left.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left)

        right_split = QSplitter(Qt.Orientation.Vertical)
        self.properties = PropertiesPanel(self.ctl)
        self.results = ResultsPanel(self.ctl)
        right_split.addWidget(self.properties)
        right_split.addWidget(self.results)
        right_split.setSizes([330, 570])
        right = QDockWidget("Info", self)
        right.setObjectName("info")
        right.setWidget(right_split)
        right.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right)
        self.resizeDocks([left, right], [220, 380], Qt.Orientation.Horizontal)

    def _action(self, text, slot, shortcut=None, tip=""):
        act = QAction(text, self)
        act.triggered.connect(slot)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        if tip:
            act.setToolTip(tip)
            act.setStatusTip(tip)
        return act

    def _build_actions(self):
        self.act_open = self._action("Open…", self.open_project, QKeySequence.StandardKey.Open)
        self.act_save = self._action("Save", self.save_project, QKeySequence.StandardKey.Save)
        self.act_save_as = self._action("Save as…", self.save_project_as, QKeySequence.StandardKey.SaveAs)
        self.act_export = self._action("Export NEC deck…", self.export_nec,
                                       tip="Export a .nec file to cross-check in 4nec2 or similar")
        self.act_quit = self._action("Quit", self.close, QKeySequence.StandardKey.Quit)
        self.act_undo = self.ctl.undo_stack.createUndoAction(self, "Undo")
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.act_redo = self.ctl.undo_stack.createRedoAction(self, "Redo")
        self.act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.act_remove = self._action("Remove part", self.remove_selected_part, QKeySequence.StandardKey.Delete)
        self.act_run = self._action("▶ Run", self.run_simulation, "F5", "Run the NEC2 simulation (F5)")
        self.act_tune = self._action("Tune…", self.open_tuner, tip="Tune a parameter for resonance")
        self.act_coil = self._action("Coil calculator…", self.open_coil_calculator)
        self.act_fit = self._action("Fit diagram", self._fit_views, "F")

        self.part_actions = {}
        for kind, ptype in PART_TYPES.items():
            act = self._action(f"Add {ptype.label}", lambda _=False, k=kind: self.ctl.add_part(k))
            self.part_actions[kind] = act

        self.units_group = QActionGroup(self)
        self.act_metric = QAction("Metric", self, checkable=True)
        self.act_imperial = QAction("Imperial", self, checkable=True)
        for act, units in ((self.act_metric, METRIC), (self.act_imperial, IMPERIAL)):
            self.units_group.addAction(act)
            act.triggered.connect(lambda _=False, u=units: self.ctl.set_units(u))
        self._sync_units_actions(self.ctl.project.units)

    def _build_toolbar_and_menus(self):
        new_menu = QMenu("New", self)
        for t in all_templates():
            new_menu.addAction(self._action(t.name, lambda _=False, tid=t.id: self.new_project(tid),
                                            tip=t.description))

        menu_file = self.menuBar().addMenu("&File")
        menu_file.addMenu(new_menu)
        for a in (self.act_open, self.act_save, self.act_save_as, None, self.act_export, None, self.act_quit):
            menu_file.addSeparator() if a is None else menu_file.addAction(a)
        menu_edit = self.menuBar().addMenu("&Edit")
        for a in (self.act_undo, self.act_redo, None, self.act_remove):
            menu_edit.addSeparator() if a is None else menu_edit.addAction(a)
        self.menu_insert = self.menuBar().addMenu("&Insert")
        for a in self.part_actions.values():
            self.menu_insert.addAction(a)
        menu_sim = self.menuBar().addMenu("&Simulate")
        for a in (self.act_run, self.act_tune, self.act_coil):
            menu_sim.addAction(a)
        menu_view = self.menuBar().addMenu("&View")
        menu_view.addAction(self.act_fit)
        menu_view.addSeparator()
        menu_view.addAction(self.act_metric)
        menu_view.addAction(self.act_imperial)

        tb = QToolBar("Main", self)
        tb.setObjectName("main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(tb)
        new_button = QToolButton()
        new_button.setText("New")
        new_button.setMenu(new_menu)
        new_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        tb.addWidget(new_button)
        tb.addAction(self.act_open)
        tb.addAction(self.act_save)
        tb.addSeparator()
        # Plain-text copies so the toolbar doesn't resize with the command name.
        stack = self.ctl.undo_stack
        for text, slot, signal, state in (("Undo", stack.undo, stack.canUndoChanged, stack.canUndo),
                                          ("Redo", stack.redo, stack.canRedoChanged, stack.canRedo)):
            act = self._action(text, slot)
            act.setEnabled(state())
            signal.connect(act.setEnabled)
            tb.addAction(act)
        tb.addSeparator()
        for a in self.part_actions.values():
            tb.addAction(a)
        tb.addAction(self.act_remove)
        tb.addSeparator()
        tb.addWidget(QLabel(" Design "))
        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setDecimals(4)
        self.freq_spin.setRange(0.1, 3000)
        self.freq_spin.setSuffix(" MHz")
        self.freq_spin.setKeyboardTracking(False)
        self.freq_spin.setValue(self.ctl.project.simulation["design_mhz"])
        self.freq_spin.valueChanged.connect(self._design_freq_edited)
        tb.addWidget(self.freq_spin)
        tb.addAction(self.act_run)
        self.auto_run = QCheckBox("Auto-run")
        self.auto_run.setChecked(self.settings.value("auto_run", True, type=bool))
        self.auto_run.toggled.connect(lambda v: self.settings.setValue("auto_run", v))
        tb.addWidget(self.auto_run)
        tb.addSeparator()
        tb.addAction(self.act_tune)
        tb.addAction(self.act_coil)

    # ---- document events ------------------------------------------------------

    def _on_model_changed(self):
        self._refresh_views()
        self._update_part_actions()
        self._update_title()
        if self.auto_run.isChecked():
            self.auto_timer.start()

    def _on_value_changed(self, node_id, key):
        if node_id == NODE_SIMULATION and key == "design_mhz":
            self.freq_spin.blockSignals(True)
            self.freq_spin.setValue(self.ctl.project.simulation["design_mhz"])
            self.freq_spin.blockSignals(False)

    def _design_freq_edited(self, value):
        self.ctl.set_value(NODE_SIMULATION, "design_mhz", value, merge_token="toolbar:freq")

    def _refresh_views(self):
        self.view3d.set_model(self.ctl.built.model)
        self._update_part_actions()

    def _update_part_actions(self):
        project = self.ctl.project
        for kind, act in self.part_actions.items():
            act.setVisible(kind in project.template.allowed_parts)
            act.setEnabled(project.can_add_part(kind))
        self.act_remove.setEnabled(self.ctl.selected in {p.id for p in project.parts})

    def _sync_units_actions(self, units):
        (self.act_imperial if units == IMPERIAL else self.act_metric).setChecked(True)

    def _update_title(self):
        name = self.path.name if self.path else "Untitled"
        dirty = "" if self.ctl.undo_stack.isClean() else " •"
        self.setWindowTitle(f"{name}{dirty} — AntennaSim")

    def _fit_views(self):
        self.side_view.fit()
        self.top_view.fit()

    # ---- simulation -------------------------------------------------------------

    def run_simulation(self):
        if self._running:
            self._rerun = True
            return
        if self.ctl.built.has_errors:
            self.results.set_simulation(self.sim, stale=True)
            self.results.set_status("Fix the errors under Model checks to simulate.")
            return
        self._running = True
        self._latest = next(self._generation)
        job = _SimJob(self._latest, self.ctl.project.clone(), self.backend)
        job.signals.done.connect(self._sim_done)
        job.signals.failed.connect(self._sim_failed)
        self.statusBar().showMessage("Simulating…")
        QThreadPool.globalInstance().start(job)

    def _finish_run(self):
        self._running = False
        if self._rerun:
            self._rerun = False
            self.run_simulation()

    def _sim_done(self, generation, sim):
        self.sim = sim
        stale = self._rerun
        self.results.set_simulation(sim, stale=stale)
        self.results.set_status("")
        self.sweep_plots.show_simulation(sim, self.ctl.project.simulation["swr_threshold"])
        self.pattern_plots.show_simulation(sim)
        self.view3d.set_model(sim.built.model)
        self.view3d.set_simulation(sim)
        self.statusBar().showMessage(
            f"Simulated {len(sim.freqs) + 1} frequencies, {sim.summary.segments} segments", 5000)
        self._finish_run()

    def _sim_failed(self, generation, message):
        self.results.set_simulation(self.sim, stale=True)
        self.results.set_status(message)
        self.statusBar().showMessage(message, 8000)
        self._finish_run()

    def open_tuner(self):
        if self.backend.executable is None:
            QMessageBox.warning(self, "Solver missing", "nec2c was not found.")
            return
        TuneDialog(self.ctl, self.backend, self).exec()

    def open_coil_calculator(self):
        CoilDialog(self.ctl, self).exec()

    def remove_selected_part(self):
        self.ctl.remove_part(self.ctl.selected)

    # ---- files -------------------------------------------------------------------

    def _confirm_discard(self) -> bool:
        if self.ctl.undo_stack.isClean():
            return True
        answer = QMessageBox.question(
            self, "Unsaved changes", "Save changes to the current design?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def _load(self, project: Project, path: Path | None):
        self.path = path
        self.sim = None
        self.ctl.set_project(project)
        self.freq_spin.blockSignals(True)
        self.freq_spin.setValue(project.simulation["design_mhz"])
        self.freq_spin.blockSignals(False)
        self.results.set_simulation(None)
        self.sweep_plots.show_simulation(None)
        self.pattern_plots.show_simulation(None)
        self.view3d.set_simulation(None)
        self._fit_views()
        self._update_title()
        self.run_simulation()

    def new_project(self, template_id: str):
        if self._confirm_discard():
            self._load(Project.new(template_id), None)

    def open_project(self):
        if not self._confirm_discard():
            return
        start = self.settings.value("last_dir", str(Path.home()))
        name, _ = QFileDialog.getOpenFileName(self, "Open design", start, FILE_FILTER)
        if not name:
            return
        try:
            project = load_project(name)
        except Exception as e:
            QMessageBox.critical(self, "Could not open", str(e))
            return
        self.settings.setValue("last_dir", str(Path(name).parent))
        self._load(project, Path(name))

    def save_project(self) -> bool:
        if self.path is None:
            return self.save_project_as()
        try:
            save_project(self.ctl.project, self.path)
        except OSError as e:
            QMessageBox.critical(self, "Could not save", str(e))
            return False
        self.ctl.undo_stack.setClean()
        self._update_title()
        self.statusBar().showMessage(f"Saved {self.path}", 4000)
        return True

    def save_project_as(self) -> bool:
        start = str(self.path or Path(self.settings.value("last_dir", str(Path.home()))) / f"design{EXTENSION}")
        name, _ = QFileDialog.getSaveFileName(self, "Save design", start, FILE_FILTER)
        if not name:
            return False
        path = Path(name)
        if path.suffix != EXTENSION:
            path = path.with_suffix(EXTENSION)
        self.path = path
        self.settings.setValue("last_dir", str(path.parent))
        return self.save_project()

    def export_nec(self):
        if self.ctl.built.has_errors:
            QMessageBox.warning(self, "Export", "Fix the model errors before exporting.")
            return
        start = str((self.path.with_suffix(".nec") if self.path else Path.home() / "antenna.nec"))
        name, _ = QFileDialog.getSaveFileName(self, "Export NEC deck", start, "NEC deck (*.nec)")
        if name:
            export_nec(self.ctl.project, name)
            self.statusBar().showMessage(f"Exported {name}", 4000)

    def closeEvent(self, event):
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
