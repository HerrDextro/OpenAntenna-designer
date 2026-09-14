"""Export a project as a NEC2 card deck for cross-checking in other tools."""

from __future__ import annotations

from pathlib import Path

from ..engine import build
from ..model.document import Project
from ..solver.nec_deck import export_deck


def export_nec(project: Project, path: str | Path | None = None) -> str:
    built = build(project)
    sim = project.simulation
    comments = [f"Exported from AntennaSim, template: {project.template.name}"]
    if built.ground_loss_ohm is not None:
        comments.append("Ground-mounted over real ground: exported over perfect ground with "
                        f"{built.ground_loss_ohm:.1f} ohm ground-loss load at the feed")
    text = export_deck(built.solver_model(), sim["sweep_start"], sim["sweep_stop"],
                       sim["sweep_points"], sim["design_mhz"], project.name, comments)
    if path is not None:
        Path(path).write_text(text)
    return text
