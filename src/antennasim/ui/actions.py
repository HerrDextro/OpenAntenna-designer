"""Shared menu building for the part tree and the diagram context menu."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from ..model.parts import PART_TYPES
from .controller import DocumentController


def populate_part_menu(ctl: DocumentController, menu: QMenu, part_id: str | None) -> None:
    """Add/remove entries for `part_id` (a part, a fixed node, or None)."""
    project = ctl.project
    parts = {p.id for p in project.parts}
    if part_id in parts:
        part = project.part(part_id)
        remove = QAction(f"Remove {part.label}", menu)
        remove.triggered.connect(lambda: ctl.remove_part(part.id))
        menu.addAction(remove)
        menu.addSeparator()
    for kind, ptype in PART_TYPES.items():
        if kind not in project.template.allowed_parts:
            continue
        act = QAction(f"Add {ptype.label}", menu)
        act.setEnabled(project.can_add_part(kind))
        act.triggered.connect(lambda _=False, k=kind: ctl.add_part(k))
        menu.addAction(act)
