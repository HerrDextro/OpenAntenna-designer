"""Load and save .antsim project files (JSON)."""

from __future__ import annotations

import json
from pathlib import Path

from ..model.document import Project

EXTENSION = ".antsim"


def save_project(project: Project, path: str | Path) -> None:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(project.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)


def load_project(path: str | Path) -> Project:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Project.from_dict(data)
