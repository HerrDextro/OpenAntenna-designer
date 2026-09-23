"""Empty state: no antenna type chosen and no design open."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCommandLinkButton, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..templates import all_templates


def _template_card(template) -> QCommandLinkButton:
    """A title + description choice button (QCommandLinkButton lays both out for us)."""
    button = QCommandLinkButton(template.name, template.description)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return button


class WelcomeView(QWidget):
    """Start screen shown when no design is open."""

    template_chosen = Signal(str)
    open_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        row = QHBoxLayout()
        outer.addLayout(row)
        outer.addStretch(2)
        row.addStretch(1)

        card = QFrame()
        card.setMaximumWidth(620)
        column = QVBoxLayout(card)
        column.setSpacing(10)
        row.addWidget(card)
        row.addStretch(1)

        title = QLabel("AntennaSim")
        title.setStyleSheet("font-size: 24px; font-weight: 600;")
        subtitle = QLabel("Design an antenna, then simulate SWR, impedance and radiation "
                          "pattern with NEC2.")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: palette(mid);")
        column.addWidget(title)
        column.addWidget(subtitle)

        pick = QLabel("Start a new design")
        pick.setStyleSheet("font-weight: 600; padding-top: 10px;")
        column.addWidget(pick)
        for template in all_templates():
            button = _template_card(template)
            button.clicked.connect(lambda _=False, t=template.id: self.template_chosen.emit(t))
            column.addWidget(button)

        column.addSpacing(6)
        open_button = QPushButton("Open a saved design…")
        open_button.clicked.connect(self.open_requested.emit)
        column.addWidget(open_button)

        hint = QLabel("Tip: drag the orange handles in the diagram to change dimensions, "
                      "and use Tune… to find resonance.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid); padding-top: 8px;")
        column.addWidget(hint)
