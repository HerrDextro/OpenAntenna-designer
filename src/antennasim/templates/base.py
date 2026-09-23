"""Template interface.

A template turns project parameters into a WireModel and describes the
editable handles and dimensions for the 2D diagram. Templates stay Qt-free;
the UI draws the wire model projection and the handles described here.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..geometry.validation import Issue
from ..geometry.wire_model import Vec3, WireModel
from ..model.params import ParamSpec

if TYPE_CHECKING:
    from ..model.document import Project

Vec2 = tuple[float, float]

SIDE = "side"  # x horizontal, z vertical
TOP = "top"  # x horizontal, y vertical

EPS = 1e-6


def max_coil_uh(freq_mhz: float, max_reactance_ohm: float = 5000.0) -> float:
    """Upper inductance bound for tuning: a coil reactance of a few kΩ covers even
    very short loaded antennas."""
    return max_reactance_ohm / (2 * math.pi * freq_mhz)


def polar_point(length: float, azimuth_deg: float, droop_deg: float, origin: Vec3) -> Vec3:
    """Point `length` away from origin at an azimuth, sloping down by `droop_deg`."""
    az, dr = math.radians(azimuth_deg), math.radians(droop_deg)
    horiz = length * math.cos(dr)
    return (origin[0] + horiz * math.cos(az),
            origin[1] + horiz * math.sin(az),
            origin[2] - length * math.sin(dr))


@dataclass(frozen=True)
class BuildContext:
    segment_length: float  # target segment length at the highest frequency, m


@dataclass(frozen=True)
class Handle:
    """A draggable point that edits one parameter.

    new_value = value + dot(drag_delta, axis), where drag_delta is in metres in
    the view's 2D coordinates.
    """

    view: str
    node_id: str
    key: str
    pos: Vec2
    axis: Vec2
    value: float
    label: str


@dataclass(frozen=True)
class Dimension:
    view: str
    p1: Vec2
    p2: Vec2
    value_m: float
    label: str = ""
    offset_px: float = 0.0  # perpendicular screen offset, positive = left of p1->p2


def add_run(model: WireModel, p1: Vec3, p2: Vec3, radius: float, name: str, ctx: "BuildContext",
            part_id: str = "antenna", coil=None, coil_distance: float = 0.0) -> int:
    """Add a straight conductor from p1 to p2, optionally broken by a loading coil.

    The coil becomes a short single-segment wire carrying a series RLC load, as
    long as a normal segment so NEC2 sees a uniform segmentation. Returns the
    index of the first wire added.
    """
    from ..geometry.wire_model import Load, Wire, distance

    length = distance(p1, p2)
    u = tuple((p2[i] - p1[i]) / length for i in range(3))

    def at(d: float) -> Vec3:
        return (p1[0] + u[0] * d, p1[1] + u[1] * d, p1[2] + u[2] * d)

    sections: list[tuple[float, float, bool]] = []
    cursor = 0.0
    if coil is not None:
        coil_len = min(ctx.segment_length, length / 3)
        start = min(max(coil_distance - coil_len / 2, 0.0), length - coil_len)
        if start > EPS:
            sections.append((0.0, start, False))
        sections.append((start, start + coil_len, True))
        cursor = start + coil_len
    if length - cursor > EPS:
        sections.append((cursor, length, False))

    first = len(model.wires)
    for d0, d1, is_coil in sections:
        index = model.add_wire(Wire(at(d0), at(d1), radius,
                                    "Loading coil" if is_coil else name,
                                    part_id=coil.id if is_coil else part_id,
                                    segments=1 if is_coil else 0))
        if is_coil:
            model.loads.append(Load(index, 0.5, l_uh=coil.params["inductance"],
                                    q=coil.params["q"], name="Loading coil", part_id=coil.id))
    return first


@dataclass(frozen=True)
class Decoration:
    """Diagram-only line for things that are not wires, e.g. buried radials."""

    view: str
    p1: Vec2
    p2: Vec2
    part_id: str
    dashed: bool = True


@dataclass(frozen=True)
class CutItem:
    name: str
    quantity: int
    length_m: float
    note: str = ""


@dataclass(frozen=True)
class Tunable:
    node_id: str
    key: str
    label: str
    minimum: float
    maximum: float


class AntennaTemplate(ABC):
    id: str
    name: str
    description: str
    specs: tuple[ParamSpec, ...]
    allowed_parts: tuple[str, ...] = ()

    def apply_defaults(self, project: "Project") -> None:
        """Add default parts to a freshly created project."""

    @abstractmethod
    def build(self, project: "Project", ctx: BuildContext) -> WireModel:
        """Return an unsegmented wire model (ground and loss are added later)."""

    def feed_is_grounded(self, project: "Project") -> bool:
        return False

    def handles(self, project: "Project") -> list[Handle]:
        return []

    def dimensions(self, project: "Project") -> list[Dimension]:
        return []

    def decorations(self, project: "Project") -> list[Decoration]:
        return []

    def cut_list(self, project: "Project") -> list[CutItem]:
        return []

    def tunables(self, project: "Project") -> list[Tunable]:
        return []

    def validate(self, project: "Project") -> list[Issue]:
        return []
