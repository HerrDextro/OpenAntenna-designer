"""Main window: toolbar on top, part tree left, diagram/plots centre, info right."""

from __future__ import annotations

import itertools
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QDockWidget, QDoubleSpinBox, QFileDialog, QLabel,
                               QMainWindow, QMenu, QMessageBox, QProgressBar, QSplitter,
                               QStackedWidget, QTabWidget, QToolBar, QToolButton, QWidget)

from ..engine import SimulationBlocked, simulate
from ..fileio.nec_export import export_nec
from ..fileio.project_file import EXTENSION, load_project, save_project
from ..model.document import NODE_SIMULATION, Project
from ..model.parts import PART_TYPES
from ..model.units import IMPERIAL, METRIC
from ..solver.nec2_backend import Nec2Backend
from ..templates import all_templates
from ..templates.base import SIDE, TOP
from .compare import ComparePanel, ReferenceStore
from .controller import DocumentController
from .cut_list_view import CutListView
from .diagram import DiagramView
from .part_tree import PartTree
from .plots import PatternPlots, SweepPlots
from .properties_panel import PropertiesPanel
from .results_panel import ResultsPanel
from .tools import CoilDialog, TuneDialog
from .view3d import View3D
from .welcome import WelcomeView

FILE_FILTER = f"AntennaSim project (*{EXTENSION})"
WATCHDOG_MS = 120_000  # a solve that never reports back must not freeze the UI


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
        # A placeholder project keeps the panels valid while the empty state is
        # shown; `has_document` says whether the user actually has a design open.
        self.ctl = DocumentController(project or Project.new("monopole"), self)
        self.references = ReferenceStore(self)
        self.has_document = project is not None
        self.path: Path | None = None
        self.sim = None
        self._generation = itertools.count(1)
        self._latest = 0
        self._running = False
        self._rerun = False
        # Jobs must be referenced while they run: if Python collects the job its
        # signal object dies with it and the result never arrives.
        self._jobs: set[_SimJob] = set()
        self.settings = QSettings("AntennaSim", "AntennaSim")

        self._build_central()
        self._build_docks()
        self._build_actions()
        self._build_toolbar_and_menus()

        self.auto_timer = QTimer(self, singleShot=True, interval=400)
        self.auto_timer.timeout.connect(self.run_simulation)
        self.watchdog = QTimer(self, singleShot=True, interval=WATCHDOG_MS)
        self.watchdog.timeout.connect(self._watchdog_fired)
        self.ctl.model_changed.connect(self._on_model_changed)
        self.ctl.value_changed.connect(self._on_value_changed)
        self.ctl.selection_changed.connect(lambda _: self._update_part_actions())
        self.ctl.undo_stack.cleanChanged.connect(lambda _: self._update_title())
        self.ctl.units_changed.connect(self._sync_units_actions)
        self.references.changed.connect(self._refresh_comparison)

        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)  # indeterminate
        self.busy_bar.setMaximumWidth(140)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.hide()
        self.busy_label = QLabel()
        self.statusBar().addPermanentWidget(self.busy_label)
        self.statusBar().addPermanentWidget(self.busy_bar)
        self.statusBar().showMessage(f"Solver: {self.backend.name}"
                                     if self.backend.executable else
                                     "nec2c not found: build it with third_party/build_nec2c.py")
        self.resize(1500, 900)
        self._apply_document_state()
        self._refresh_views()
        if self.has_document:
            QTimer.singleShot(0, self.run_simulation)

    # ---- layout -------------------------------------------------------------

    def _build_central(self):
        self.stack = QStackedWidget()
        self.welcome = WelcomeView()
        self.welcome.template_chosen.connect(self.new_project)
        self.welcome.open_requested.connect(self.open_project)
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
        self.cut_list = CutListView(self.ctl)
        self.tabs.addTab(self.cut_list, "Cut list")
        self.stack.addWidget(self.welcome)
        self.stack.addWidget(self.tabs)
        self.setCentralWidget(self.stack)

    def _build_docks(self):
        self.tree = PartTree(self.ctl)
        left = self.left_dock = QDockWidget("Parts", self)
        left.setObjectName("parts")
        left.setWidget(self.tree)
        left.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left)

        right_split = QSplitter(Qt.Orientation.Vertical)
        self.properties = PropertiesPanel(self.ctl)
        self.results = ResultsPanel(self.ctl)
        self.compare_panel = ComparePanel(self.references)
        self.compare_panel.add_button.clicked.connect(self.save_reference)
        self.results.bottom_tabs.addTab(self.compare_panel, "Compare")
        right_split.addWidget(self.properties)
        right_split.addWidget(self.results)
        right_split.setSizes([330, 570])
        right = self.right_dock = QDockWidget("Info", self)
        right.setObjectName("info")
        right.setWidget(right_split)
        right.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right)
        self.resizeDocks([left, right], [220, 430], Qt.Orientation.Horizontal)

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
        self.act_close = self._action("Close design", self.close_document,
                                      QKeySequence.StandardKey.Close,
                                      tip="Close the design and return to the start screen")
        self.act_quit = self._action("Quit", self.close, QKeySequence.StandardKey.Quit)
        self.act_undo = self.ctl.undo_stack.createUndoAction(self, "Undo")
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.act_redo = self.ctl.undo_stack.createRedoAction(self, "Redo")
        self.act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.act_remove = self._action("Remove part", self.remove_selected_part, QKeySequence.StandardKey.Delete)
        self.act_run = self._action("▶ Run", self.run_simulation, "F5", "Run the NEC2 simulation (F5)")
        self.act_tune = self._action("Tune…", self.open_tuner, tip="Tune a parameter for resonance")
        self.act_coil = self._action("Coil calculator…", self.open_coil_calculator)
        self.act_reference = self._action(
            "Save reference", self.save_reference, "Ctrl+R",
            tip="Remember this design and its results, then compare later changes against it")
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
        for a in (self.act_open, self.act_save, self.act_save_as, None, self.act_export,
                  self.act_close, None, self.act_quit):
            menu_file.addSeparator() if a is None else menu_file.addAction(a)
        menu_edit = self.menuBar().addMenu("&Edit")
        for a in (self.act_undo, self.act_redo, None, self.act_remove):
            menu_edit.addSeparator() if a is None else menu_edit.addAction(a)
        self.menu_insert = self.menuBar().addMenu("&Insert")
        for a in self.part_actions.values():
            self.menu_insert.addAction(a)
        menu_sim = self.menuBar().addMenu("&Simulate")
        for a in (self.act_run, self.act_tune, self.act_coil, self.act_reference):
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
        tb.addAction(self.act_reference)

    # ---- document events ------------------------------------------------------

    def _on_model_changed(self):
        self._refresh_views()
        self._update_part_actions()
        self._update_title()
        if self.has_document and self.auto_run.isChecked():
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
            act.setVisible(self.has_document and project.part_allowed(kind))
            act.setEnabled(self.has_document and project.can_add_part(kind))
        self.act_remove.setEnabled(self.has_document
                                   and self.ctl.selected in {p.id for p in project.parts})

    def _apply_document_state(self):
        """Switch between the empty state and an open design."""
        open_doc = self.has_document
        self.stack.setCurrentIndex(1 if open_doc else 0)
        self.left_dock.setVisible(open_doc)
        self.right_dock.setVisible(open_doc)
        for act in (self.act_save, self.act_save_as, self.act_export, self.act_close,
                    self.act_run, self.act_tune, self.act_coil, self.act_fit,
                    self.act_reference, self.act_undo, self.act_redo):
            act.setEnabled(open_doc)
        self.freq_spin.setEnabled(open_doc)
        self.auto_run.setEnabled(open_doc)
        self._update_part_actions()
        self._update_title()

    def close_document(self):
        """Close the current design and return to the empty state."""
        if not self.has_document or not self._confirm_discard():
            return
        self.auto_timer.stop()
        self.watchdog.stop()
        self.has_document = False
        self.path = None
        self.sim = None
        self.references.clear()
        self._rerun = False
        self.ctl.set_project(Project.new(self.ctl.project.template_id))
        self.results.set_simulation(None)
        self.results.set_status("")
        self.sweep_plots.show_simulation(None)
        self.pattern_plots.show_simulation(None)
        self.view3d.set_simulation(None)
        self._set_busy(False)
        self._apply_document_state()
        self.statusBar().showMessage("Design closed", 4000)

    def _sync_units_actions(self, units):
        (self.act_imperial if units == IMPERIAL else self.act_metric).setChecked(True)

    def _sync_name_with_path(self):
        """Name the design after its file, so copied text and headers match."""
        if self.path is not None:
            self.ctl.project.name = self.path.stem

    def _update_title(self):
        if not self.has_document:
            self.setWindowTitle("AntennaSim")
            return
        name = self.path.name if self.path else "Untitled"
        dirty = "" if self.ctl.undo_stack.isClean() else " •"
        self.setWindowTitle(f"{name}{dirty} - AntennaSim")

    def _fit_views(self):
        self.side_view.fit()
        self.top_view.fit()

    # ---- simulation -------------------------------------------------------------

    def run_simulation(self):
        if not self.has_document:
            return
        if self._running:
            self._rerun = True
            return
        if self.ctl.built.has_errors:
            self.results.set_simulation(self.sim, stale=True)
            self.results.set_status("Fix the errors under Model checks to simulate.", error=True)
            self.statusBar().showMessage("Model has errors: see Model checks.", 8000)
            return
        self._running = True
        self._latest = next(self._generation)
        job = _SimJob(self._latest, self.ctl.project.clone(), self.backend)
        job.signals.done.connect(self._sim_done)
        job.signals.failed.connect(self._sim_failed)
        job.signals.done.connect(lambda *_, j=job: self._jobs.discard(j))
        job.signals.failed.connect(lambda *_, j=job: self._jobs.discard(j))
        self._jobs.add(job)
        self._set_busy(True)
        QThreadPool.globalInstance().start(job)

    def _set_busy(self, busy: bool):
        self.busy_bar.setVisible(busy)
        self.busy_label.setText("Solving…" if busy else "")
        self.results.set_busy(busy)
        # Run stays enabled on purpose: if a solve is ever lost, the user can
        # always start another one instead of facing a dead button.
        if busy:
            self.watchdog.start()
        else:
            self.watchdog.stop()

    def _watchdog_fired(self):
        if self._running:
            self._sim_failed(self._latest, "The solver did not respond. Press Run to try again.")

    def _finish_run(self):
        self._running = False
        if self._rerun:
            self._rerun = False
            self.run_simulation()
        else:
            self._set_busy(False)

    def _sim_done(self, generation, sim):
        if generation != self._latest:  # a superseded run must not overwrite newer results
            self._finish_run()
            return
        self.sim = sim
        stale = self._rerun
        self.results.set_simulation(sim, stale=stale)
        self.results.set_status("")
        shown = self.references.visible()
        self.sweep_plots.show_simulation(sim, self.ctl.project.simulation["swr_threshold"], shown)
        self.pattern_plots.show_simulation(sim, shown)
        self.view3d.set_model(sim.built.model)
        self.view3d.set_simulation(sim)
        changed = len(self.results.changed)
        note = f", {changed} value(s) changed" if changed else ""
        self.statusBar().showMessage(
            f"Simulated {len(sim.freqs) + 1} frequencies, "
            f"{sim.summary.segments} segments{note}", 6000)
        self._finish_run()

    def _sim_failed(self, generation, message):
        if generation != self._latest and self._running:
            self._finish_run()
            return
        self.results.set_simulation(self.sim, stale=True)
        self.results.set_status(message, error=True)
        self.statusBar().showMessage(message, 15000)
        self._finish_run()

    def save_reference(self):
        """Snapshot the current design and results to compare later changes against."""
        if self.sim is None:
            self.statusBar().showMessage("Run a simulation before saving a reference.", 5000)
            return
        if not self.references.can_add():
            self.statusBar().showMessage("Remove a reference first.", 5000)
            return
        rows = {label: value for label, value, _ in self.results._summary_rows()}
        name = self.path.stem if self.path else f"Ref {len(self.references.references) + 1}"
        if any(r.name == name for r in self.references.references):
            name = f"{name} ({len(self.references.references) + 1})"
        self.references.add(name, self.ctl.project, self.sim, rows)
        self.results.bottom_tabs.setCurrentWidget(self.compare_panel)
        self.statusBar().showMessage(f"Saved reference “{name}”", 5000)

    def _refresh_comparison(self):
        shown = self.references.visible()
        count = len(self.references.references)
        self.results.bottom_tabs.setTabText(
            self.results.bottom_tabs.indexOf(self.compare_panel),
            f"Compare ({count})" if count else "Compare")
        self.results.set_baseline(self.references.baseline())
        if self.sim is not None:
            self.sweep_plots.show_simulation(self.sim,
                                             self.ctl.project.simulation["swr_threshold"], shown)
            self.pattern_plots.show_simulation(self.sim, shown)

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
        self.references.clear()
        self.has_document = True
        self._sync_name_with_path()
        self._apply_document_state()
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
        self._sync_name_with_path()
        try:
            save_project(self.ctl.project, self.path)
        except OSError as e:
            QMessageBox.critical(self, "Could not save", str(e))
            return False
        self.ctl.undo_stack.setClean()
        self._update_title()
        self.statusBar().showMessage(f"Saved {self.path}", 4000)
        self.properties.show_node(self.ctl.selected)  # header may carry the new name
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
        if not self._confirm_discard():
            event.ignore()
            return
        # Stop signals that would otherwise fire while the window is torn down.
        self.watchdog.stop()
        self.auto_timer.stop()
        try:
            self.ctl.undo_stack.cleanChanged.disconnect()
        except RuntimeError:
            pass
        event.accept()
