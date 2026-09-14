"""Application entry point: `antennasim [file.antsim]` or `python -m antennasim`."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from .fileio.project_file import load_project
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("AntennaSim")
    app.setStyle("Fusion")
    # The diagram and plots are drawn on light backgrounds; keep the chrome consistent.
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)

    project = None
    path = None
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
        path = Path(sys.argv[1])
        project = load_project(path)
    window = MainWindow(project)
    if path is not None:
        window.path = path
        window._update_title()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
