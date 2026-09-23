"""Left panel: tree of the antenna, its parts and the project settings nodes."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem

from ..model.document import NODE_ANTENNA, NODE_ENVIRONMENT, NODE_FEEDLINE, NODE_SIMULATION
from .actions import populate_part_menu
from .controller import DocumentController

_ROLE = Qt.ItemDataRole.UserRole


class PartTree(QTreeWidget):
    def __init__(self, ctl: DocumentController, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.itemSelectionChanged.connect(self._on_select)
        ctl.structure_changed.connect(lambda _: self.rebuild())
        ctl.selection_changed.connect(self._select_node)
        self._updating = False
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.rebuild()

    def rebuild(self):
        self._updating = True
        self.clear()
        project = self.ctl.project
        antenna = QTreeWidgetItem([project.template.name])
        antenna.setData(0, _ROLE, NODE_ANTENNA)
        self.addTopLevelItem(antenna)
        for part in project.parts:
            item = QTreeWidgetItem([part.label])
            item.setData(0, _ROLE, part.id)
            antenna.addChild(item)
        for node, label in ((NODE_ENVIRONMENT, "Ground & materials"),
                            (NODE_FEEDLINE, "Feed system"),
                            (NODE_SIMULATION, "Frequencies")):
            item = QTreeWidgetItem([label])
            item.setData(0, _ROLE, node)
            self.addTopLevelItem(item)
        self.expandAll()
        self._updating = False
        self._select_node(self.ctl.selected)

    def _items(self):
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.child(i) for i in range(item.childCount()))

    def _select_node(self, node_id: str):
        self._updating = True
        if not node_id:
            self.clearSelection()
            self.setCurrentItem(None)
        else:
            for item in self._items():
                if item.data(0, _ROLE) == node_id:
                    self.setCurrentItem(item)
                    break
        self._updating = False

    def _on_select(self):
        if self._updating:
            return
        items = self.selectedItems()
        self.ctl.select(items[0].data(0, _ROLE) if items else None)

    def mousePressEvent(self, event):
        # Clicking empty space deselects, which shows the overview.
        if self.itemAt(event.pos()) is None:
            self.clearSelection()
            self.setCurrentItem(None)
            self.ctl.select(None)
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.clearSelection()
            self.setCurrentItem(None)
            self.ctl.select(None)
            return
        super().keyPressEvent(event)

    def _context_menu(self, pos):
        item = self.itemAt(pos)
        node = item.data(0, _ROLE) if item is not None else None
        if node:
            self.ctl.select(node)
        menu = QMenu(self)
        populate_part_menu(self.ctl, menu, node)
        menu.exec(self.viewport().mapToGlobal(pos))
