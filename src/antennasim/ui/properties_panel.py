"""Right panel (top): editor generated from the selected node's ParamSpecs."""

from __future__ import annotations

from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QLabel,
                               QSpinBox, QVBoxLayout, QWidget)

from ..model.params import ParamSpec
from ..model.units import from_display, to_display, unit_label
from .controller import DocumentController

_DECIMALS = {"length": 3, "small_length": 2, "angle": 1, "frequency": 4, "inductance": 3,
             "resistance": 2, "float": 3}
_STEPS = {"length": 0.05, "small_length": 0.5, "angle": 5.0, "frequency": 0.05,
          "inductance": 0.5, "resistance": 1.0, "float": 0.1}


class PropertiesPanel(QWidget):
    def __init__(self, ctl: DocumentController, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600; font-size: 13px; padding: 2px 0 6px 0;")
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.form_host)
        layout.addStretch(1)
        self.editors: dict[str, tuple[ParamSpec, QWidget, QLabel]] = {}
        self.node_id = ""

        ctl.selection_changed.connect(self.show_node)
        ctl.structure_changed.connect(lambda _: self.show_node(ctl.selected))
        ctl.value_changed.connect(self._on_value_changed)
        ctl.units_changed.connect(lambda _: self.show_node(self.node_id))
        self.show_node(ctl.selected)

    # ---- construction ------------------------------------------------------

    def show_node(self, node_id: str):
        project = self.ctl.project
        try:
            specs = project.node_specs(node_id)
        except KeyError:
            node_id = "antenna"
            specs = project.node_specs(node_id)
        self.node_id = node_id
        while self.form.rowCount():
            self.form.removeRow(0)
        self.editors.clear()

        titles = {"antenna": project.template.name, "environment": "Ground & materials",
                  "feedline": "Feed system", "simulation": "Frequencies"}
        self.title.setText(titles.get(node_id) or project.part(node_id).label)

        values = project.node_values(node_id)
        for spec in specs:
            editor = self._make_editor(spec)
            label = QLabel(spec.label)
            if spec.help:
                label.setToolTip(spec.help)
                editor.setToolTip(spec.help)
            self.form.addRow(label, editor)
            self.editors[spec.key] = (spec, editor, label)
            self._load(spec.key, values[spec.key])
        self._update_visibility()

    def _make_editor(self, spec: ParamSpec) -> QWidget:
        units = self.ctl.project.units
        if spec.kind == "bool":
            w = QCheckBox()
            w.toggled.connect(lambda v, k=spec.key: self._commit(k, v))
        elif spec.kind == "choice":
            w = QComboBox()
            for value, label in spec.choices:
                w.addItem(label, value)
            w.currentIndexChanged.connect(lambda _i, k=spec.key, w=w: self._commit(k, w.currentData()))
        elif spec.kind == "int":
            w = QSpinBox()
            w.setRange(int(spec.minimum if spec.minimum is not None else -10**6),
                       int(spec.maximum if spec.maximum is not None else 10**6))
            w.setKeyboardTracking(False)
            w.valueChanged.connect(lambda v, k=spec.key: self._commit(k, v, merge=True))
        else:
            w = QDoubleSpinBox()
            decimals = _DECIMALS.get(spec.kind, 3)
            lo = spec.minimum if spec.minimum is not None else -1e6
            hi = spec.maximum if spec.maximum is not None else 1e6
            w.setDecimals(decimals)
            w.setRange(to_display(spec.kind, lo, units), to_display(spec.kind, hi, units))
            w.setSingleStep(_STEPS.get(spec.kind, 0.1))
            suffix = unit_label(spec.kind, units)
            if suffix:
                w.setSuffix(f" {suffix}")
            w.setKeyboardTracking(False)
            w.valueChanged.connect(
                lambda v, k=spec.key, kind=spec.kind: self._commit(k, from_display(kind, v, self.ctl.project.units), merge=True))
        return w

    def _load(self, key: str, value):
        spec, w, _ = self.editors[key]
        with QSignalBlocker(w):
            if spec.kind == "bool":
                w.setChecked(bool(value))
            elif spec.kind == "choice":
                w.setCurrentIndex(max(w.findData(value), 0))
            elif spec.kind == "int":
                w.setValue(int(value))
            else:
                w.setValue(to_display(spec.kind, value, self.ctl.project.units))

    def _update_visibility(self):
        values = self.ctl.project.node_values(self.node_id)

        def visible(spec: ParamSpec) -> bool:
            # A field is hidden if the field controlling it is hidden too.
            if not spec.is_visible(values):
                return False
            parent = spec.visible_when and self.editors.get(spec.visible_when[0])
            return visible(parent[0]) if parent else True

        for spec, w, label in self.editors.values():
            shown = visible(spec)
            w.setVisible(shown)
            label.setVisible(shown)

    # ---- sync ------------------------------------------------------------

    def _commit(self, key: str, value, merge: bool = False):
        token = f"edit:{self.node_id}:{key}" if merge else None
        self.ctl.set_value(self.node_id, key, value, merge_token=token)

    def _on_value_changed(self, node_id: str, key: str):
        if node_id != self.node_id or key not in self.editors:
            return
        self._load(key, self.ctl.project.node_values(node_id)[key])
        self._update_visibility()
