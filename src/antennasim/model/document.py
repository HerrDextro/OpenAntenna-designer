"""The project document: everything that is saved to a .antsim file."""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field
from typing import Any

from .params import ParamSpec, defaults
from .parts import ENVIRONMENT_SPECS, FEEDLINE_SPECS, PART_TYPES, SIMULATION_SPECS

FILE_VERSION = 1


def _coerce_all(specs: tuple[ParamSpec, ...], values: dict[str, Any]) -> dict[str, Any]:
    out = defaults(specs)
    for s in specs:
        if s.key in values:
            out[s.key] = s.coerce(values[s.key])
    return out


@dataclass
class Part:
    kind: str
    id: str
    params: dict[str, Any]

    @property
    def type(self):
        return PART_TYPES[self.kind]

    @property
    def label(self) -> str:
        return self.type.label


# Fixed node ids used by the UI and undo commands.
NODE_ANTENNA = "antenna"
NODE_ENVIRONMENT = "environment"
NODE_FEEDLINE = "feedline"
NODE_SIMULATION = "simulation"


@dataclass
class Project:
    template_id: str
    name: str = "Untitled antenna"
    antenna: dict[str, Any] = field(default_factory=dict)
    parts: list[Part] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    feedline: dict[str, Any] = field(default_factory=dict)
    simulation: dict[str, Any] = field(default_factory=dict)
    units: str = "metric"
    notes: str = ""

    def __post_init__(self):
        self.antenna = _coerce_all(self.template.specs, self.antenna)
        self.environment = _coerce_all(ENVIRONMENT_SPECS, self.environment)
        self.feedline = _coerce_all(FEEDLINE_SPECS, self.feedline)
        self.simulation = _coerce_all(SIMULATION_SPECS, self.simulation)
        for p in self.parts:
            p.params = _coerce_all(PART_TYPES[p.kind].specs, p.params)

    @classmethod
    def new(cls, template_id: str) -> "Project":
        project = cls(template_id=template_id)
        project.template.apply_defaults(project)
        return project

    @property
    def template(self):
        from ..templates import get_template

        return get_template(self.template_id)

    # ---- generic node access -------------------------------------------

    def node_specs(self, node_id: str) -> tuple[ParamSpec, ...]:
        if node_id == NODE_ANTENNA:
            return self.template.specs
        if node_id == NODE_ENVIRONMENT:
            return ENVIRONMENT_SPECS
        if node_id == NODE_FEEDLINE:
            return FEEDLINE_SPECS
        if node_id == NODE_SIMULATION:
            return SIMULATION_SPECS
        return self.part(node_id).type.specs

    def node_values(self, node_id: str) -> dict[str, Any]:
        if node_id == NODE_ANTENNA:
            return self.antenna
        if node_id == NODE_ENVIRONMENT:
            return self.environment
        if node_id == NODE_FEEDLINE:
            return self.feedline
        if node_id == NODE_SIMULATION:
            return self.simulation
        return self.part(node_id).params

    def set_value(self, node_id: str, key: str, value: Any) -> Any:
        spec = next(s for s in self.node_specs(node_id) if s.key == key)
        coerced = spec.coerce(value)
        self.node_values(node_id)[key] = coerced
        return coerced

    # ---- parts ---------------------------------------------------------

    def part(self, part_id: str) -> Part:
        for p in self.parts:
            if p.id == part_id:
                return p
        raise KeyError(part_id)

    def parts_of(self, kind: str) -> list[Part]:
        return [p for p in self.parts if p.kind == kind]

    def first_part(self, kind: str) -> Part | None:
        found = self.parts_of(kind)
        return found[0] if found else None

    def can_add_part(self, kind: str) -> bool:
        if kind not in self.template.allowed_parts:
            return False
        return len(self.parts_of(kind)) < PART_TYPES[kind].max_count

    def add_part(self, kind: str, params: dict[str, Any] | None = None) -> Part:
        if not self.can_add_part(kind):
            raise ValueError(f"cannot add another {kind}")
        taken = {p.id for p in self.parts}
        part_id = next(f"{kind}{i}" for i in itertools.count(1) if f"{kind}{i}" not in taken)
        part = Part(kind, part_id, _coerce_all(PART_TYPES[kind].specs, params or {}))
        self.parts.append(part)
        return part

    def remove_part(self, part_id: str) -> Part:
        part = self.part(part_id)
        self.parts.remove(part)
        return part

    # ---- serialisation -------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": FILE_VERSION,
            "name": self.name,
            "template": self.template_id,
            "antenna": dict(self.antenna),
            "parts": [{"kind": p.kind, "id": p.id, "params": dict(p.params)} for p in self.parts],
            "environment": dict(self.environment),
            "feedline": dict(self.feedline),
            "simulation": dict(self.simulation),
            "units": self.units,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        version = data.get("version", 1)
        if version > FILE_VERSION:
            raise ValueError(f"file version {version} is newer than this program supports")
        parts = [
            Part(p["kind"], p["id"], dict(p.get("params", {})))
            for p in data.get("parts", [])
            if p.get("kind") in PART_TYPES
        ]
        return cls(
            template_id=data["template"],
            name=data.get("name", "Untitled antenna"),
            antenna=dict(data.get("antenna", {})),
            parts=parts,
            environment=dict(data.get("environment", {})),
            feedline=dict(data.get("feedline", {})),
            simulation=dict(data.get("simulation", {})),
            units=data.get("units", "metric"),
            notes=data.get("notes", ""),
        )

    def clone(self) -> "Project":
        return copy.deepcopy(self)
