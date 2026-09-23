"""Comparison references: snapshots of a design and its results, overlaid on the plots."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from ..engine import Simulation
from ..model.document import Project

# Distinct from the live curves (blue/orange), and distinguishable from each other.
REFERENCE_COLORS = ["#7b5cd6", "#2ca02c", "#d62728", "#8c8c8c"]
MAX_REFERENCES = 4


@dataclass
class Reference:
    name: str
    project: Project
    simulation: Simulation
    color: str
    visible: bool = True
    summary_rows: dict[str, str] = field(default_factory=dict)


class ReferenceStore(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.references: list[Reference] = []

    def can_add(self) -> bool:
        return len(self.references) < MAX_REFERENCES

    def add(self, name: str, project: Project, simulation: Simulation,
            summary_rows: dict[str, str]) -> Reference | None:
        if not self.can_add():
            return None
        used = {r.color for r in self.references}
        color = next((c for c in REFERENCE_COLORS if c not in used), REFERENCE_COLORS[-1])
        ref = Reference(name, project.clone(), simulation, color, True, dict(summary_rows))
        self.references.append(ref)
        self.changed.emit()
        return ref

    def remove(self, index: int):
        if 0 <= index < len(self.references):
            del self.references[index]
            self.changed.emit()

    def clear(self):
        if self.references:
            self.references.clear()
            self.changed.emit()

    def visible(self) -> list[Reference]:
        return [r for r in self.references if r.visible]

    def baseline(self) -> Reference | None:
        """The reference that result values are compared against."""
        shown = self.visible()
        return shown[0] if shown else None


class ComparePanel(QWidget):
    """List of saved references with add/remove controls."""

    def __init__(self, store: ReferenceStore, parent=None):
        super().__init__(parent)
        self.store = store
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.hint = QLabel("Save the current design as a reference, change something, and the "
                           "plots and results show both.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.hint)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemChanged.connect(self._toggle)
        self.list.itemDoubleClicked.connect(lambda _: self.rename_selected())
        layout.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("Save current")
        self.remove_button = QPushButton("Remove")
        self.clear_button = QPushButton("Clear")
        self.remove_button.clicked.connect(self.remove_selected)
        self.clear_button.clicked.connect(store.clear)
        for b in (self.add_button, self.remove_button, self.clear_button):
            buttons.addWidget(b)
        layout.addLayout(buttons)

        store.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.list.blockSignals(True)
        self.list.clear()
        for ref in self.store.references:
            item = QListWidgetItem(f"{ref.name}  ·  {ref.project.template.name}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if ref.visible else Qt.CheckState.Unchecked)
            item.setForeground(Qt.GlobalColor.black)
            item.setData(Qt.ItemDataRole.DecorationRole, None)
            item.setToolTip(f"Colour {ref.color} · double-click to rename")
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.remove_button.setEnabled(bool(self.store.references))
        self.clear_button.setEnabled(bool(self.store.references))
        self.add_button.setEnabled(self.store.can_add())
        self.add_button.setToolTip("" if self.store.can_add()
                                   else f"At most {MAX_REFERENCES} references")

    def _toggle(self, item: QListWidgetItem):
        index = self.list.row(item)
        if 0 <= index < len(self.store.references):
            self.store.references[index].visible = item.checkState() == Qt.CheckState.Checked
            self.store.changed.emit()

    def remove_selected(self):
        row = self.list.currentRow()
        if row < 0 and self.store.references:
            row = len(self.store.references) - 1
        self.store.remove(row)

    def rename_selected(self):
        row = self.list.currentRow()
        if not 0 <= row < len(self.store.references):
            return
        ref = self.store.references[row]
        name, ok = QInputDialog.getText(self, "Rename reference", "Name:", text=ref.name)
        if ok and name.strip():
            ref.name = name.strip()
            self.store.changed.emit()
