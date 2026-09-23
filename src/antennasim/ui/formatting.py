"""Text formatting shared by the overview, the results panel and the clipboard."""

from __future__ import annotations

from typing import Any

from ..engine import Simulation
from ..model.document import (NODE_ANTENNA, NODE_ENVIRONMENT, NODE_FEEDLINE, NODE_SIMULATION,
                              Project)
from ..model.params import ParamSpec
from ..model.units import to_display, unit_label

_DECIMALS = {"length": 3, "small_length": 2, "angle": 1, "frequency": 4, "inductance": 3,
             "resistance": 2, "float": 2}


def format_param(spec: ParamSpec, value: Any, units: str) -> str:
    if spec.kind == "bool":
        return "Yes" if value else "No"
    if spec.kind == "choice":
        return next((label for key, label in spec.choices if key == value), str(value))
    if spec.kind == "int":
        return str(int(value))
    shown = to_display(spec.kind, float(value), units)
    suffix = unit_label(spec.kind, units)
    return f"{shown:.{_DECIMALS.get(spec.kind, 2)}f}{' ' + suffix if suffix else ''}"


def node_sections(project: Project) -> list[tuple[str, list[tuple[str, str]]]]:
    """[(section title, [(label, value), ...]), ...] for every editable node."""
    nodes = [(NODE_ANTENNA, project.template.name)]
    nodes += [(part.id, part.label) for part in project.parts]
    nodes += [(NODE_ENVIRONMENT, "Ground & materials"), (NODE_FEEDLINE, "Feed system"),
              (NODE_SIMULATION, "Frequencies")]
    sections = []
    for node_id, title in nodes:
        values = project.node_values(node_id)
        rows = [(spec.label, format_param(spec, values[spec.key], project.units))
                for spec in project.node_specs(node_id) if spec.is_visible(values)]
        sections.append((title, rows))
    return sections


def settings_text(project: Project) -> str:
    lines = [f"{project.name} — {project.template.name}"]
    for title, rows in node_sections(project):
        lines.append("")
        lines.append(f"[{title}]")
        lines += [f"  {label}: {value}" for label, value in rows]
    return "\n".join(lines) + "\n"


def results_text(project: Project, rows: list[tuple[str, str, str]]) -> str:
    lines = [f"{project.name} — {project.template.name} results", ""]
    lines += [f"{label}: {value}" for label, value, _ in rows]
    return "\n".join(lines) + "\n"


def cut_list_text(project: Project, rows: list[tuple[str, str, str, str]]) -> str:
    lines = [f"{project.name} — cut list", ""]
    for name, qty, length, note in rows:
        line = f"{qty} × {name}"
        if length:
            line += f": {length}"
        if note:
            line += f"  ({note})"
        lines.append(line)
    return "\n".join(lines) + "\n"


def full_report_text(project: Project, sim: Simulation | None,
                     result_rows: list[tuple[str, str, str]]) -> str:
    text = settings_text(project)
    if sim is not None:
        text += "\n" + results_text(project, result_rows)
    return text
