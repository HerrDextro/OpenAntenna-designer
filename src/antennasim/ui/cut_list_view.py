"""Centre tab: the build sheet (cut list) with room to read it."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..model.units import format_length
from .controller import DocumentController
from .formatting import cut_list_text

HEADERS = ["Item", "Quantity", "Length", "Notes"]


class CutListView(QWidget):
    def __init__(self, ctl: DocumentController, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 15px; font-weight: 600;")
        header.addWidget(self.title)
        header.addStretch(1)
        self.copy_button = QPushButton("Copy cut list")
        self.copy_button.clicked.connect(self._copy)
        header.addWidget(self.copy_button)
        layout.addLayout(header)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setStyleSheet("QTableWidget { font-size: 13px; }")
        layout.addWidget(self.table, 1)

        self.note = QLabel("Lengths are for bare wire. Insulated wire resonates a few percent "
                           "shorter, so cut long and trim while measuring.")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.note)

        ctl.model_changed.connect(self.refresh)
        ctl.units_changed.connect(lambda _: self.refresh())
        ctl.structure_changed.connect(lambda _: self.refresh())
        self.refresh()

    def rows(self) -> list[tuple[str, str, str, str]]:
        project = self.ctl.project
        out = []
        for item in project.template.cut_list(project):
            length = format_length(item.length_m, project.units) if item.length_m > 0 else ""
            out.append((item.name, str(item.quantity), length, item.note))
        return out

    def refresh(self):
        project = self.ctl.project
        self.title.setText(f"Cut list — {project.template.name}")
        rows = self.rows()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                cell = QTableWidgetItem(text)
                if c in (1, 2):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, cell)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

    def _copy(self):
        QGuiApplication.clipboard().setText(cut_list_text(self.ctl.project, self.rows()))
