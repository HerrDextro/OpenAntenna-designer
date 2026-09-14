"""The 3D thin-wire model handed to the solver.

Coordinates are metres; z is up and z = 0 is the ground surface.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Vec3 = tuple[float, float, float]


def distance(a: Vec3, b: Vec3) -> float:
    return math.dist(a, b)


def lerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


@dataclass
class Wire:
    p1: Vec3
    p2: Vec3
    radius: float
    name: str
    part_id: str = "antenna"
    segments: int = 0  # 0 = choose automatically

    @property
    def length(self) -> float:
        return distance(self.p1, self.p2)

    def segment_at(self, fraction: float) -> int:
        """1-based segment index containing the point at `fraction` along the wire."""
        n = max(self.segments, 1)
        return min(max(int(fraction * n) + 1, 1), n)


@dataclass
class Load:
    """Series RLC load on one segment. Resistance R_total = r + X_L/q."""

    wire: int  # index into WireModel.wires
    fraction: float
    r_ohm: float = 0.0
    l_uh: float = 0.0
    q: float | None = None
    name: str = ""
    part_id: str = ""

    def resistance_at(self, freq_mhz: float) -> float:
        r = self.r_ohm
        if self.q and self.l_uh > 0:
            r += 2 * math.pi * freq_mhz * 1e6 * self.l_uh * 1e-6 / self.q
        return r


@dataclass
class Source:
    wire: int
    fraction: float


@dataclass
class GroundModel:
    kind: str  # "free_space" | "perfect" | "real"
    conductivity: float = 0.0
    permittivity: float = 1.0


@dataclass
class WireModel:
    wires: list[Wire] = field(default_factory=list)
    loads: list[Load] = field(default_factory=list)
    source: Source | None = None
    ground: GroundModel = field(default_factory=lambda: GroundModel("free_space"))
    conductivity: float = math.inf  # S/m, inf = lossless

    def add_wire(self, wire: Wire) -> int:
        self.wires.append(wire)
        return len(self.wires) - 1

    def segment_endpoints(self, wire_index: int) -> list[tuple[Vec3, Vec3]]:
        w = self.wires[wire_index]
        n = max(w.segments, 1)
        return [(lerp(w.p1, w.p2, i / n), lerp(w.p1, w.p2, (i + 1) / n)) for i in range(n)]

    def bounds(self) -> tuple[Vec3, Vec3]:
        pts = [p for w in self.wires for p in (w.p1, w.p2)] or [(0.0, 0.0, 0.0)]
        lo = tuple(min(p[i] for p in pts) for i in range(3))
        hi = tuple(max(p[i] for p in pts) for i in range(3))
        return lo, hi
