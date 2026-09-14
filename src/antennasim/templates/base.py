"""Template interface.

A template turns project parameters into a WireModel and describes the
editable handles and dimensions for the 2D diagram. Templates stay Qt-free;
the UI draws the wire model projection and the handles described here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..geometry.validation import Issue
from ..geometry.wire_model import WireModel
from ..model.params import ParamSpec

if TYPE_CHECKING:
    from ..model.document import Project

Vec2 = tuple[float, float]

SIDE = "side"  # x horizontal, z vertical
TOP = "top"  # x horizontal, y vertical


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
