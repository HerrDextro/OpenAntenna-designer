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

    # Single-segment wires that carry a load (loading coils) are modelling
    # stand-ins one segment long; their length/radius says nothing physical.
    load_carriers = {load.wire for load in model.loads}

    for index, w in enumerate(model.wires):
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
        stand_in = index in load_carriers and w.segments == 1
        if w.length / w.radius < 30 and not stand_in:
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


def ground_dependence(model: WireModel, design_mhz: float, soil_label: str) -> Issue | None:
    """Say plainly when results are not free-space numbers.

    Over ground, the reflection sets gain and take-off angle, and close to it the
    soil also pulls the feed impedance around, so the user should always know
    which numbers lean on the soil setting.
    """
    if model.ground.kind == "free_space" or model.source is None:
        return None
    wire = model.wires[model.source.wire]
    feed_z = wire.p1[2] + (wire.p2[2] - wire.p1[2]) * model.source.fraction
    height_wl = feed_z / wavelength_m(design_mhz)

    if model.ground.kind == "perfect":
        return Issue(INFO, f"Not free space: perfect ground. The feed point is {height_wl:.2f} λ "
                           f"up. Gain is roughly 3 dB optimistic compared with real soil, and "
                           f"there are no ground losses.", "environment")
    where = ("sits on real ground" if height_wl < 0.01
             else f"is {height_wl:.2f} λ above real ground")
    if height_wl < 0.2:
        return Issue(WARNING, f"Not free space: the feed point {where} ({soil_label}). "
                              f"Impedance, gain and take-off angle all depend on the soil: "
                              f"try another soil to see the spread.", "environment")
    return Issue(INFO, f"Not free space: the feed point {where} ({soil_label}). The soil sets "
                       f"the pattern shape and take-off angle; the impedance is affected less "
                       f"at this height.", "environment")


def segment_distance(p1, q1, p2, q2) -> float:
    """Shortest distance between line segments p1-q1 and p2-q2 (Ericson's method)."""
    d1 = [q1[i] - p1[i] for i in range(3)]
    d2 = [q2[i] - p2[i] for i in range(3)]
    r = [p1[i] - p2[i] for i in range(3)]

    def dot(u, v):
        return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]

    a, e, f = dot(d1, d1), dot(d2, d2), dot(d2, r)
    if a < 1e-18 and e < 1e-18:
        return math.dist(p1, p2)
    if a < 1e-18:
        s, t = 0.0, min(max(f / e, 0.0), 1.0)
    else:
        c = dot(d1, r)
        if e < 1e-18:
            s, t = min(max(-c / a, 0.0), 1.0), 0.0
        else:
            b = dot(d1, d2)
            denom = a * e - b * b
            s = min(max((b * f - c * e) / denom, 0.0), 1.0) if denom > 1e-18 else 0.0
            t = (b * s + f) / e
            if t < 0:
                s, t = min(max(-c / a, 0.0), 1.0), 0.0
            elif t > 1:
                s, t = min(max((b - c) / a, 0.0), 1.0), 1.0
    c1 = [p1[i] + d1[i] * s for i in range(3)]
    c2 = [p2[i] + d2[i] * t for i in range(3)]
    return math.dist(c1, c2)


def clearance_issues(model: WireModel, checked: set[int], joined: set[int],
                     feed) -> list[Issue]:
    """Wires in `checked` (e.g. the coax) that touch, cross or run along another wire.

    NEC2 joins wires that share an end point, and only there; wires that meet
    anywhere else are not connected, and wires closer than a few radii are
    modelled poorly. `checked` wires may only share ends with the `joined`
    wires (each other, an earth lead) and with the antenna at `feed`.
    """
    issues: list[Issue] = []
    seen: set[frozenset] = set()
    for i in sorted(checked):
        wi = model.wires[i]
        found: list[Issue] = []
        for j, wj in enumerate(model.wires):
            pair = frozenset((i, j))
            if j == i or pair in seen:
                continue
            seen.add(pair)
            touching = wi.radius + wj.radius
            shared = [p for p in (wi.p1, wi.p2) for q in (wj.p1, wj.p2)
                      if math.dist(p, q) < 1e-6]
            if shared:
                joint = shared[0]
                if j not in joined and math.dist(joint, feed) > 1e-6:
                    found.append(Issue(ERROR, f"{wi.name} ends exactly on the end of {wj.name}, "
                                               f"which connects them. Move it slightly.",
                                       wi.part_id))
                    continue
                # Joined at an end: only a problem if they leave it side by side.
                far_i = wi.p2 if math.dist(wi.p1, joint) < 1e-6 else wi.p1
                far_j = wj.p2 if math.dist(wj.p1, joint) < 1e-6 else wj.p1
                ui = [(far_i[k] - joint[k]) / max(wi.length, 1e-12) for k in range(3)]
                uj = [(far_j[k] - joint[k]) / max(wj.length, 1e-12) for k in range(3)]
                cos = sum(a * b for a, b in zip(ui, uj))
                if cos > math.cos(math.radians(10)):
                    found.append(Issue(ERROR, f"{wi.name} runs along {wj.name} from where they "
                                               f"join. Lead the coax away from the antenna "
                                               f"first with a coax run.", wi.part_id))
                continue
            gap = segment_distance(wi.p1, wi.p2, wj.p1, wj.p2)
            if gap < touching:
                found.append(Issue(ERROR, f"{wi.name} touches or crosses {wj.name}. NEC2 only "
                                           f"connects wires at their ends; reroute it.", wi.part_id))
            elif gap < 3 * touching:
                found.append(Issue(WARNING, f"{wi.name} passes within {gap * 1000:.0f} mm of "
                                             f"{wj.name}; NEC2 is inaccurate this close.",
                                    wi.part_id))
        # A coax lying along a leg also "touches" the coil in that leg, and a leg
        # split by a coil is several wires: say the most useful thing once.
        along = [x for x in found if "runs along" in x.message]
        for issue in along or found:
            if issue not in issues:
                issues.append(issue)
    return issues
