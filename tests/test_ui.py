"""Offscreen UI smoke tests."""

import os

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
    w.auto_run.setChecked(False)
    w.show()
    app.processEvents()
    yield w
    QThreadPool.globalInstance().waitForDone(30000)
    app.processEvents()
    w.ctl.undo_stack.setClean()
    w.close()


def wait_for_run(app, window):
    QThreadPool.globalInstance().waitForDone(30000)
    for _ in range(20):
        app.processEvents()
    assert not window._running


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
