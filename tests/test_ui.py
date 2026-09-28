"""Offscreen UI smoke tests."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QThreadPool  # noqa: E402

from antennasim.model.document import NODE_ANTENNA  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def window(app, backend):
    from antennasim.ui.main_window import MainWindow

    w = MainWindow()
    w.new_project("monopole")  # the app starts in the empty state
    w.auto_run.setChecked(False)
    w.show()
    app.processEvents()
    yield w
    QThreadPool.globalInstance().waitForDone(30000)
    app.processEvents()
    w.ctl.undo_stack.setClean()
    w.close()


def wait_for_run(app, window, timeout_s: float = 60.0):
    """Wait until no simulation is running; a finished run may queue another."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        QThreadPool.globalInstance().waitForDone(5000)
        for _ in range(20):
            app.processEvents()
        if not window._running:
            return
    raise AssertionError("simulation did not finish")


def test_empty_state_on_startup(app, backend):
    from antennasim.ui.main_window import MainWindow

    w = MainWindow()
    w.show()
    app.processEvents()
    try:
        assert not w.has_document
        assert w.stack.currentWidget() is w.welcome
        assert not w.left_dock.isVisible() and not w.right_dock.isVisible()
        for act in (w.act_run, w.act_save, w.act_export, w.act_tune, w.act_close):
            assert not act.isEnabled(), act.text()
        assert w.windowTitle() == "AntennaSim"
        w.run_simulation()  # must be a no-op, not a crash
        assert not w._running and w.sim is None

        # Choosing a template from the start screen opens a design.
        w.welcome.template_chosen.emit("dipole")
        wait_for_run(app, w)
        assert w.has_document and w.stack.currentWidget() is w.tabs
        assert w.left_dock.isVisible() and w.act_run.isEnabled()
        assert w.ctl.project.template_id == "dipole"
        assert w.sim is not None

        # Closing returns to the empty state and clears the results.
        w.ctl.undo_stack.setClean()
        w.close_document()
        assert not w.has_document
        assert w.stack.currentWidget() is w.welcome
        assert w.sim is None and w.results.sim is None
        assert not w.act_run.isEnabled()
    finally:
        w.ctl.undo_stack.setClean()
        w.close()


def test_initial_run_fills_results(app, window):
    wait_for_run(app, window)
    assert window.sim is not None
    assert window.results.stale is False


def test_edit_undo_redo(app, window):
    ctl = window.ctl
    h0 = ctl.project.antenna["height"]
    ctl.set_value(NODE_ANTENNA, "height", h0 + 1.0)
    assert ctl.project.antenna["height"] == pytest.approx(h0 + 1.0)
    assert window.results.stale
    ctl.undo_stack.undo()
    assert ctl.project.antenna["height"] == pytest.approx(h0)
    ctl.undo_stack.redo()
    assert ctl.project.antenna["height"] == pytest.approx(h0 + 1.0)


def test_drag_merges_into_one_undo_step(app, window):
    ctl = window.ctl
    before = ctl.undo_stack.count()
    for v in (5.1, 5.2, 5.3, 5.4):
        ctl.set_value(NODE_ANTENNA, "height", v, merge_token="drag99")
    assert ctl.undo_stack.count() == before + 1
    ctl.undo_stack.undo()
    assert ctl.project.antenna["height"] == pytest.approx(5.0)


def test_add_remove_parts_updates_tree(app, window):
    ctl = window.ctl
    ctl.add_part("top_hat")
    ctl.add_part("loading_coil")
    labels = [window.tree.topLevelItem(0).child(i).text(0)
              for i in range(window.tree.topLevelItem(0).childCount())]
    assert "Capacitive top hat" in labels and "Loading coil" in labels
    assert ctl.selected == "loading_coil1"
    assert window.properties.title.text() == "Loading coil"
    window.remove_selected_part()
    assert ctl.project.first_part("loading_coil") is None
    ctl.undo_stack.undo()
    assert ctl.project.first_part("loading_coil") is not None


def test_properties_panel_edits_model(app, window):
    ctl = window.ctl
    ctl.select(NODE_ANTENNA)
    spec, editor, _ = window.properties.editors["height"]
    editor.setValue(6.25)
    assert ctl.project.antenna["height"] == pytest.approx(6.25)
    ctl.set_units("imperial")
    spec, editor, _ = window.properties.editors["height"]
    assert editor.value() == pytest.approx(6.25 / 0.3048, rel=1e-3)
    assert editor.suffix().strip() == "ft"


def test_tune_dialog_applies_value(app, window):
    from antennasim.ui.tools import TuneDialog

    ctl = window.ctl
    dlg = TuneDialog(ctl, window.backend, window)
    dlg.param.setCurrentIndex(0)  # vertical length
    dlg._run()
    QThreadPool.globalInstance().waitForDone(60000)
    for _ in range(20):
        app.processEvents()
    assert dlg._value is not None, dlg.result.text()
    dlg._apply()
    assert ctl.project.antenna["height"] == pytest.approx(dlg._value)
    ctl.undo_stack.undo()
    assert ctl.project.antenna["height"] == pytest.approx(5.0)


def test_coil_dialog(app, window):
    from antennasim.ui.tools import CoilDialog

    window.ctl.add_part("loading_coil", {"inductance": 20.0})
    dlg = CoilDialog(window.ctl, window)
    assert dlg.inductance.value() == pytest.approx(20.0)
    assert "turns" in dlg.output.text()


def test_context_menu_removes_and_adds_parts(app, window):
    from PySide6.QtWidgets import QMenu

    from antennasim.ui.actions import populate_part_menu

    ctl = window.ctl
    menu = QMenu()
    populate_part_menu(ctl, menu, "radials1")
    texts = [a.text() for a in menu.actions() if a.text()]
    assert texts[0] == "Remove Radials"
    menu.actions()[0].trigger()
    assert ctl.project.first_part("radials") is None

    menu = QMenu()
    populate_part_menu(ctl, menu, None)
    add_hat = next(a for a in menu.actions() if a.text() == "Add Capacitive top hat")
    add_hat.trigger()
    assert ctl.project.first_part("top_hat") is not None
    # A part already at its limit cannot be added twice.
    menu = QMenu()
    populate_part_menu(ctl, menu, None)
    assert not next(a for a in menu.actions() if a.text() == "Add Capacitive top hat").isEnabled()


def test_busy_indicator_and_changed_values(app, window):
    wait_for_run(app, window)
    assert not window.busy_bar.isVisible() and window.act_run.isEnabled()
    assert window.results.changed == {}  # nothing to compare against on the first run

    window._set_busy(True)
    assert window.busy_bar.isVisible()
    assert "Solving" in window.busy_label.text()
    assert window.act_run.isEnabled()  # never leave the user with a dead Run button
    window._set_busy(False)
    assert not window.busy_bar.isVisible()

    window.ctl.set_value(NODE_ANTENNA, "height", 5.4)
    assert window.results.stale
    window.run_simulation()
    wait_for_run(app, window)
    assert not window.results.stale
    assert "Impedance (antenna)" in window.results.changed
    assert not window.busy_bar.isVisible()


def test_solver_failure_is_reported_and_recovers(app, window):
    from antennasim.solver.base import SolverBackend
    from antennasim.solver.results import SolverError

    class Broken(SolverBackend):
        name = "broken"

        def solve(self, request):
            raise SolverError("NEC2 failed: boom")

    wait_for_run(app, window)
    good = window.backend
    window.backend = Broken()
    window.run_simulation()
    wait_for_run(app, window)
    assert "boom" in window.results.status.text()
    assert window.results.stale
    assert not window.busy_bar.isVisible()
    assert window.act_run.isEnabled()

    # A later good run clears the error.
    window.backend = good
    window.run_simulation()
    wait_for_run(app, window)
    assert window.results.status.text() == ""
    assert not window.results.stale


def test_watchdog_unsticks_a_lost_run(app, window):
    wait_for_run(app, window)
    window._running = True  # pretend a job vanished without reporting back
    window._set_busy(True)
    window._watchdog_fired()
    assert not window._running
    assert not window.busy_bar.isVisible()
    assert "did not respond" in window.results.status.text()
    window.run_simulation()
    wait_for_run(app, window)
    assert window.sim is not None


def test_dipole_project_in_ui(app, window):
    from antennasim.templates import all_templates

    assert {t.id for t in all_templates()} >= {"monopole", "dipole"}
    window.new_project("dipole")
    wait_for_run(app, window)
    assert window.ctl.project.template_id == "dipole"
    assert window.tree.topLevelItem(0).text(0) == "Dipole"
    assert "leg_length" in window.properties.editors
    assert window.sim is not None and window.sim.summary.max_gain_dbi > 3
    for i in range(window.tabs.count()):
        window.tabs.setCurrentIndex(i)
        app.processEvents()
        window.tabs.currentWidget().grab()


def test_full_run_with_all_parts_and_views(app, window, tmp_path):
    ctl = window.ctl
    ctl.add_part("top_hat", {"length": 0.8})
    ctl.add_part("loading_coil", {"height": 1.0, "inductance": 2.0})
    wait_for_run(app, window)
    window.run_simulation()
    wait_for_run(app, window)
    assert window.sim is not None and window.sim.summary.wires > 5
    for i in range(window.tabs.count()):
        window.tabs.setCurrentIndex(i)
        app.processEvents()
        window.tabs.currentWidget().grab()
    window.path = tmp_path / "t.antsim"
    assert window.save_project()
    assert (tmp_path / "t.antsim").exists()


def test_overview_when_nothing_selected(app, window):
    from antennasim.ui.formatting import settings_text

    ctl = window.ctl
    ctl.select(None)
    assert window.properties.title.text().startswith("Overview")
    assert window.properties.copy_button.isVisibleTo(window.properties)
    assert not window.properties.editors  # read-only listing, no editors

    text = settings_text(ctl.project)
    assert "Droop angle: 30.0" in text      # a radials setting
    assert "Vertical length: 5.000 m" in text  # an antenna setting
    assert "[Ground & materials]" in text and "[Feed system]" in text

    # Selecting a part again brings the editors back.
    ctl.select("radials1")
    assert "length" in window.properties.editors
    assert window.properties.title.text() == "Radials"


def test_copy_buttons_put_text_on_the_clipboard(app, window):
    from PySide6.QtGui import QGuiApplication

    wait_for_run(app, window)
    clipboard = QGuiApplication.clipboard()

    clipboard.clear()
    window.results.copy_button.click()
    results = clipboard.text()
    assert "Impedance (antenna)" in results and "Max gain" in results

    clipboard.clear()
    window.cut_list.copy_button.click()
    cut = clipboard.text()
    assert "cut list" in cut and "Vertical element" in cut

    clipboard.clear()
    window.ctl.select(None)
    window.properties.copy_button.click()
    assert "Vertical length" in clipboard.text()


def test_cut_list_has_its_own_tab(app, window):
    titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert "Cut list" in titles
    rows = window.cut_list.rows()
    assert rows and rows[0][0] == "Vertical element"
    assert window.cut_list.table.rowCount() == len(rows)
    # The right-hand panel no longer carries a cramped copy of it.
    bottom = [window.results.bottom_tabs.tabText(i)
              for i in range(window.results.bottom_tabs.count())]
    assert not any(t.startswith("Cut list") for t in bottom)


def test_comparison_overlays_and_deltas(app, window):
    wait_for_run(app, window)
    before = window.sim.summary.z_antenna

    window.save_reference()
    assert len(window.references.references) == 1
    ref = window.references.references[0]
    assert ref.summary_rows["Impedance (antenna)"]

    window.ctl.set_value(NODE_ANTENNA, "height", 5.6)
    window.run_simulation()
    wait_for_run(app, window)
    assert window.sim.summary.z_antenna != before

    # Results compare against the reference, plots show both curves.
    assert window.results.baseline is ref
    grid = window.results.grid
    deltas = []
    for r in range(grid.rowCount()):
        item = grid.itemAtPosition(r, 2)
        # The banner spans all three columns; only real delta cells sit alone here.
        if item is not None and grid.itemAtPosition(r, 1) is not item:
            deltas.append(item.widget().text())
    assert deltas, "no delta column rendered"
    assert all(d.startswith("(") and d.endswith(")") for d in deltas), deltas
    assert any("+" in d or "-" in d for d in deltas), deltas
    assert len(window.sweep_plots.swr_plot.plotItem.curves) >= 3  # live + reference

    # Hiding the reference removes the comparison again.
    ref.visible = False
    window.references.changed.emit()
    assert window.results.baseline is None

    window.references.clear()
    assert not window.references.references


def test_manual_zoom_survives_a_rerun_and_reset_refits(app, window):
    wait_for_run(app, window)
    plots = window.sweep_plots
    plot = plots.swr_plot
    f_lo, f_hi = float(window.sim.freqs[0]), float(window.sim.freqs[-1])

    # An automatic fit after a run leaves the whole sweep visible.
    shown = plot.viewRange()[0]
    assert shown[0] <= f_lo + 1e-6 and shown[1] >= f_hi - 1e-6

    # A zoom the user made by hand is kept, so you can watch one region.
    plot.setXRange(f_lo + 0.4, f_lo + 0.5, padding=0)
    plots.user_zoomed = True
    window.ctl.set_value(NODE_ANTENNA, "height", 5.15)
    window.run_simulation()
    wait_for_run(app, window)
    kept = plot.viewRange()[0]
    assert kept[1] - kept[0] < 0.3, kept

    # Reset zoom (also bound to a double-click) fits the sweep again.
    plots.reset_zoom()
    assert not plots.user_zoomed
    refit = plot.viewRange()[0]
    assert refit[0] <= f_lo + 1e-6 and refit[1] >= f_hi - 1e-6


def test_new_sweep_range_discards_an_old_zoom(app, window):
    wait_for_run(app, window)
    plots = window.sweep_plots
    plots.swr_plot.setXRange(14.0, 14.1, padding=0)
    plots.user_zoomed = True

    window.ctl.set_value("simulation", "sweep_start", 20.0)
    window.ctl.set_value("simulation", "sweep_stop", 22.0)
    window.run_simulation()
    wait_for_run(app, window)
    assert not plots.user_zoomed
    shown = plots.swr_plot.viewRange()[0]
    assert shown[0] <= 20.0 + 1e-6 and shown[1] >= 22.0 - 1e-6, shown


def test_saved_design_takes_its_file_name(app, window, tmp_path):
    from antennasim.ui.formatting import settings_text

    assert window.ctl.project.name == "Untitled antenna"
    window.path = tmp_path / "CB vertical.antsim"
    assert window.save_project()
    assert window.ctl.project.name == "CB vertical"
    assert settings_text(window.ctl.project).startswith("CB vertical")
    assert window.windowTitle().startswith("CB vertical.antsim")
    assert "—" not in window.windowTitle()
    assert window.windowTitle().endswith("- AntennaSim")

    # Re-opening keeps the name.
    from antennasim.fileio.project_file import load_project

    assert load_project(tmp_path / "CB vertical.antsim").name == "CB vertical"


def test_swr_axis_frames_the_dip_then_falls_back_to_the_data(app, window):
    import numpy as np

    # Wide sweep around a resonant vertical: a deep dip with high edges. The axis
    # should frame the dip, letting the edges run off the top, rather than
    # squashing the whole curve flat to fit the worst value.
    window.ctl.set_value("simulation", "sweep_start", 10.0)
    window.ctl.set_value("simulation", "sweep_stop", 20.0)
    window.run_simulation()
    wait_for_run(app, window)
    best = float(np.min(window.sim.swr_rig))
    peak = float(np.max(window.sim.swr_rig))
    assert best < 2 < 10 < peak  # a real dip with badly matched edges

    y_lo, y_hi = window.sweep_plots.swr_plot.viewRange()[1]
    assert y_lo <= 1.5
    assert y_hi >= best * 1.2, (y_hi, best)  # the dip and its shape are visible
    assert y_hi < peak, (y_hi, peak)         # not scaled down to fit the worst value

    # When even the best SWR is high there is no dip to frame, so fit the data
    # and keep the curve on screen.
    window.ctl.set_value(NODE_ANTENNA, "height", 1.2)
    window.ctl.set_value("simulation", "sweep_start", 13.5)
    window.ctl.set_value("simulation", "sweep_stop", 15.0)
    window.run_simulation()
    wait_for_run(app, window)
    peak = float(np.max(window.sim.swr_rig))
    assert float(np.min(window.sim.swr_rig)) > 10
    assert window.sweep_plots.swr_plot.viewRange()[1][1] >= peak, peak
