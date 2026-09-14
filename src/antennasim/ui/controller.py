"""Document controller: owns the project, applies undoable edits and notifies views."""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from ..engine import BuiltModel, build
from ..model.document import (NODE_ANTENNA, NODE_ENVIRONMENT, NODE_FEEDLINE, NODE_SIMULATION,
                              Part, Project)

FIXED_NODES = (NODE_ANTENNA, NODE_ENVIRONMENT, NODE_FEEDLINE, NODE_SIMULATION)

_MERGE_ID = 1001
_MERGE_WINDOW_S = 1.5


class SetValueCommand(QUndoCommand):
    def __init__(self, ctl: "DocumentController", node_id: str, key: str, old: Any, new: Any,
                 merge_token: str | None):
        spec = next(s for s in ctl.project.node_specs(node_id) if s.key == key)
        super().__init__(f"Change {spec.label}")
        self.ctl, self.node_id, self.key = ctl, node_id, key
        self.old, self.new = old, new
        self.merge_token = merge_token
        self.stamp = time.monotonic()

    def id(self) -> int:
        return _MERGE_ID if self.merge_token else -1

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, SetValueCommand):
            return False
        if (other.node_id, other.key, other.merge_token) != (self.node_id, self.key, self.merge_token):
            return False
        # A drag is always one undo step; typed edits merge only when rapid.
        if not self.merge_token.startswith("drag") and other.stamp - self.stamp > _MERGE_WINDOW_S:
            return False
        self.new = other.new
        self.stamp = other.stamp
        return True

    def redo(self):
        self.ctl._apply_value(self.node_id, self.key, self.new)

    def undo(self):
        self.ctl._apply_value(self.node_id, self.key, self.old)


class AddPartCommand(QUndoCommand):
    def __init__(self, ctl: "DocumentController", kind: str, params: dict | None = None):
        super().__init__("Add part")
        self.ctl, self.kind, self.params = ctl, kind, params
        self.part: Part | None = None
        self.index = 0

    def redo(self):
        p = self.ctl.project
        if self.part is None:
            self.part = p.add_part(self.kind, self.params)
            self.index = len(p.parts) - 1
            self.setText(f"Add {self.part.label}")
        else:
            p.parts.insert(self.index, self.part)
        self.ctl._structure_changed(self.part.id)

    def undo(self):
        self.ctl.project.parts.remove(self.part)
        self.ctl._structure_changed(NODE_ANTENNA)


class RemovePartCommand(QUndoCommand):
    def __init__(self, ctl: "DocumentController", part_id: str):
        part = ctl.project.part(part_id)
        super().__init__(f"Remove {part.label}")
        self.ctl, self.part = ctl, part
        self.index = ctl.project.parts.index(part)

    def redo(self):
        self.ctl.project.parts.remove(self.part)
        self.ctl._structure_changed(NODE_ANTENNA)

    def undo(self):
        self.ctl.project.parts.insert(self.index, self.part)
        self.ctl._structure_changed(self.part.id)


class DocumentController(QObject):
    """Signals:
    value_changed(node_id, key): a parameter changed
    structure_changed(select_node_id): parts added/removed or a new project loaded
    model_changed(): any change; `built` has been refreshed
    selection_changed(node_id)
    """

    value_changed = Signal(str, str)
    structure_changed = Signal(str)
    model_changed = Signal()
    selection_changed = Signal(str)
    units_changed = Signal(str)

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self.undo_stack = QUndoStack(self)
        self.selected = NODE_ANTENNA
        self.built: BuiltModel = build(project)

    # ---- public edits -----------------------------------------------------

    def set_value(self, node_id: str, key: str, value: Any, merge_token: str | None = None):
        values = self.project.node_values(node_id)
        old = values[key]
        spec = next(s for s in self.project.node_specs(node_id) if s.key == key)
        new = spec.coerce(value)
        if new == old:
            return
        self.undo_stack.push(SetValueCommand(self, node_id, key, old, new, merge_token))

    def add_part(self, kind: str, params: dict | None = None):
        if self.project.can_add_part(kind):
            self.undo_stack.push(AddPartCommand(self, kind, params))

    def remove_part(self, part_id: str):
        try:
            self.project.part(part_id)
        except KeyError:
            return
        self.undo_stack.push(RemovePartCommand(self, part_id))

    def set_project(self, project: Project):
        self.project = project
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self._structure_changed(NODE_ANTENNA)
        self.units_changed.emit(project.units)

    def set_units(self, units: str):
        if units != self.project.units:
            self.project.units = units
            self.units_changed.emit(units)

    def select(self, node_id: str):
        if node_id != self.selected:
            self.selected = node_id
            self.selection_changed.emit(node_id)

    # ---- internal ---------------------------------------------------------

    def _rebuild(self):
        self.built = build(self.project)
        self.model_changed.emit()

    def _apply_value(self, node_id: str, key: str, value: Any):
        self.project.node_values(node_id)[key] = value
        self.value_changed.emit(node_id, key)
        self._rebuild()

    def _structure_changed(self, select_node: str):
        valid = {p.id for p in self.project.parts} | set(FIXED_NODES)
        if self.selected not in valid:
            self.selected = NODE_ANTENNA
        self.structure_changed.emit(select_node)
        self._rebuild()
        self.select(select_node)
