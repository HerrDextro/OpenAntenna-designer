"""Model validity checks.

NEC2 silently gives wrong answers when its thin-wire assumptions are broken,
so these rules are surfaced to the user as warnings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..model.units import wavelength_m
from .wire_model import WireModel

ERROR = "error"
WARNING = "warning"
INFO = "info"


@dataclass(frozen=True)
class Issue:
    level: str
    message: str
    node_id: str = ""


def _key(p) -> tuple[float, float, float]:
    return (round(p[0], 6), round(p[1], 6), round(p[2], 6))


def validate_model(model: WireModel, freq_min_mhz: float, freq_max_mhz: float) -> list[Issue]:
    issues: list[Issue] = []
    lam_max_f = wavelength_m(freq_max_mhz)
    lam_min_f = wavelength_m(freq_min_mhz)

    if not model.wires:
        return [Issue(ERROR, "The model has no wires.")]
    if model.source is None:
        issues.append(Issue(ERROR, "The model has no feed point."))

    reported: set[tuple[str, str]] = set()

    def once(level, msg, node):
        if (msg, node) not in reported:
            reported.add((msg, node))
            issues.append(Issue(level, msg, node))

    for w in model.wires:
        if w.length < 1e-6:
            once(ERROR, f"{w.name}: zero-length wire.", w.part_id)
            continue
        if w.radius <= 0:
            once(ERROR, f"{w.name}: wire diameter must be positive.", w.part_id)
            continue
        n = max(w.segments, 1)
        seg = w.length / n
        if seg > lam_max_f / 10 + 1e-9:
            once(WARNING, f"{w.name}: segments longer than λ/10 at {freq_max_mhz:g} MHz. "
                          "Increase segments per wavelength.", w.part_id)
        if seg < 2 * w.radius:
            once(WARNING, f"{w.name}: segment length is under 2× the wire radius "
                          "(thin-wire approximation breaks down). Use a thinner wire "
                          "or fewer segments.", w.part_id)
        elif seg < 8 * w.radius:
            once(INFO, f"{w.name}: segment length / radius below 8, accuracy is reduced.",
                 w.part_id)
        if w.length / w.radius < 30:
            once(WARNING, f"{w.name}: very fat conductor for its length.", w.part_id)

    # Segment length ratio at junctions.
    ends: dict[tuple, list[tuple[int, float]]] = {}
    for i, w in enumerate(model.wires):
        seg = w.length / max(w.segments, 1)
        ends.setdefault(_key(w.p1), []).append((i, seg))
        ends.setdefault(_key(w.p2), []).append((i, seg))
    for joined in ends.values():
        if len(joined) < 2:
            continue
        lengths = [s for _, s in joined]
        if max(lengths) / min(lengths) > 5:
            names = ", ".join(sorted({model.wires[i].name for i, _ in joined}))
            once(WARNING, f"Segment lengths differ by more than 5× at the junction of {names}.",
                 model.wires[joined[0][0]].part_id)

    # Ground proximity.
    if model.ground.kind != "free_space":
        clearance = max(1e-3 * lam_min_f, 0.0)
        for w in model.wires:
            for p in (w.p1, w.p2):
                if p[2] < -1e-9:
                    once(ERROR, f"{w.name}: wire goes below ground.", w.part_id)
                    break
            else:
                low = min(w.p1[2], w.p2[2])
                touches = math.isclose(low, 0.0, abs_tol=1e-9)
                # A wire that only touches ground at one end (a ground-fed
                # vertical) is fine; one lying along the ground is not.
                if touches and math.isclose(max(w.p1[2], w.p2[2]), 0.0, abs_tol=1e-9):
                    once(ERROR, f"{w.name}: wire lies on the ground, NEC2 cannot model this.",
                         w.part_id)
                elif not touches and low < clearance:
                    once(WARNING, f"{w.name}: closer than {clearance * 1000:.0f} mm to ground; "
                                  "NEC2 results are unreliable this close.", w.part_id)
    return issues
