"""The coax feedline as part of the antenna: its shield, route, chokes and radio end.

At HF, skin effect splits a coax into two separate conductors. The inside (centre
conductor and inner surface of the shield) is the transmission line, handled
by the feed-system maths. The outside surface of the shield is simply another
wire joined to the cold side of the feed point. Current on it is the
common-mode current: it radiates, and it detunes the antenna.

This module adds that outer surface to the wire model, following the coax runs
under the Feed system node, then a lead to the radio and optionally an earth
lead. It works for every template that reports a feed point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..analysis.coil import AirChoke, air_choke
from ..geometry.validation import ERROR, INFO, WARNING, Issue
from ..geometry.wire_model import FIXED, PARALLEL, SERIES, Load, Vec3, Wire, WireModel, distance
from ..model.document import NODE_FEEDLINE
from ..model.materials import COAX
from .base import EPS, SIDE, TOP, CutItem, Handle, along_handle, polar_point

if TYPE_CHECKING:
    from ..model.document import Part, Project

# A perfect choke is a resistance so large that no current to speak of passes.
PERFECT_CHOKE_OHM = 1e9

EARTH_LEAD_RADIUS = 1e-3


@dataclass
class Leg:
    """One straight piece of the coax route."""

    p1: Vec3
    p2: Vec3
    part_id: str
    name: str

    @property
    def length(self) -> float:
        return distance(self.p1, self.p2)


@dataclass
class ShieldInfo:
    """Where the shield ended up in the wire model."""

    wires: list[int]  # coax wires from the feed to the radio, in order
    earth_wire: int | None
    length_m: float  # modelled coax length
    # Where the choke requirement is evaluated: the choke nearest the feed, or
    # the feed itself when there is no choke.
    port: tuple[int, float]  # (wire, fraction)
    port_distance_m: float
    port_load: int | None  # index into model.loads of the choke sitting at the port
    chokes: list[tuple[str, float, int]] = field(default_factory=list)  # part id, m, load


def coax_type(project: "Project"):
    return COAX.get(project.feedline["coax"])


def is_modelled(project: "Project") -> bool:
    """True when the shield is actually added to the model."""
    fl = project.feedline
    coax = coax_type(project)
    template = project.template
    return (fl["common_mode"] and coax is not None and coax.shield_diameter_m is not None
            and template.feed_point(project) is not None
            and not template.feed_is_grounded(project))


def route(project: "Project") -> list[Leg]:
    """The coax from the feed point: each coax run, then the lead to the radio."""
    feed = project.template.feed_point(project)
    if feed is None:
        return []
    legs = []
    cursor = feed
    for i, run in enumerate(project.parts_of("coax_run")):
        p = run.params
        end = polar_point(p["length"], p["azimuth"], p["slope"], cursor)
        legs.append(Leg(cursor, end, run.id, f"Coax run {i + 1}"))
        cursor = end
    radio = radio_point(project, cursor)
    if distance(cursor, radio) > EPS:
        legs.append(Leg(cursor, radio, NODE_FEEDLINE, "Coax to radio"))
    return legs


def radio_point(project: "Project", route_end: Vec3 | None = None) -> Vec3:
    """The radio sits straight below (or above) the end of the last coax run."""
    if route_end is None:
        legs = route(project)
        if not legs:
            return (0.0, 0.0, project.feedline["radio_height"])
        route_end = legs[-1].p2
    return (route_end[0], route_end[1], project.feedline["radio_height"])


def route_length(project: "Project") -> float:
    return sum(leg.length for leg in route(project))


def feedline_length(project: "Project") -> float:
    """Coax length for loss and impedance transformation when the route is modelled:
    the route, any coax wound into chokes, and the extra length at the radio."""
    wound = sum(coil.coax_length_m for coil in
                (choke_model(project, c) for c in project.parts_of("choke")) if coil)
    return route_length(project) + wound + project.feedline["extra_length"]


def locate(legs: list[Leg], along: float) -> tuple[int, float, Vec3, Vec3]:
    """(leg index, fraction, point, unit direction) at a distance along the route."""
    remaining = max(along, 0.0)
    for i, leg in enumerate(legs):
        last = i == len(legs) - 1
        if remaining < leg.length - EPS or last:
            t = min(remaining / leg.length, 1.0) if leg.length > 0 else 0.0
            u = tuple((leg.p2[k] - leg.p1[k]) / max(leg.length, 1e-12) for k in range(3))
            point = tuple(leg.p1[k] + (leg.p2[k] - leg.p1[k]) * t for k in range(3))
            return i, t, point, u
        remaining -= leg.length
    raise ValueError("empty route")


def choke_model(project: "Project", choke: "Part") -> AirChoke | None:
    p = choke.params
    coax = coax_type(project)
    if p["choke_type"] != "air_coil" or coax is None or coax.shield_diameter_m is None:
        return None
    return air_choke(p["turns"], p["form_diameter"], coax.shield_diameter_m, p["q"],
                     project.simulation["design_mhz"])


def choke_impedance(project: "Project", choke: "Part", freq_mhz: float) -> complex:
    p = choke.params
    if p["choke_type"] == "perfect":
        return complex(PERFECT_CHOKE_OHM, 0.0)
    if p["choke_type"] == "impedance":
        return complex(p["r_ohm"], p["x_ohm"])
    return choke_model(project, choke).impedance(freq_mhz)


def _choke_load(project: "Project", choke: "Part", wire: int, fraction: float) -> Load:
    p = choke.params
    name = "Common-mode choke"
    if p["choke_type"] == "perfect":
        return Load(wire, fraction, r_ohm=PERFECT_CHOKE_OHM, kind=FIXED, name=name,
                    part_id=choke.id)
    if p["choke_type"] == "impedance":
        return Load(wire, fraction, r_ohm=p["r_ohm"], x_ohm=p["x_ohm"], kind=FIXED, name=name,
                    part_id=choke.id)
    coil = choke_model(project, choke)
    return Load(wire, fraction, r_ohm=coil.resistance_ohm, l_uh=coil.inductance_uh,
                c_pf=coil.capacitance_pf, kind=PARALLEL, name=name, part_id=choke.id)


def add_shield(model: WireModel, project: "Project") -> ShieldInfo | None:
    """Append the coax shield (and earth lead) to an unsegmented model."""
    if not is_modelled(project):
        return None
    legs = route(project)
    if not legs:
        return None
    radius = coax_type(project).shield_diameter_m / 2
    wires = [model.add_wire(Wire(leg.p1, leg.p2, radius, leg.name, part_id=leg.part_id))
             for leg in legs]
    total = sum(leg.length for leg in legs)

    chokes = []
    for choke in sorted(project.parts_of("choke"), key=lambda c: c.params["distance"]):
        along = min(choke.params["distance"], total)
        leg, fraction, _, _ = locate(legs, along)
        model.loads.append(_choke_load(project, choke, wires[leg], fraction))
        chokes.append((choke.id, along, len(model.loads) - 1))

    if chokes:
        _, port_distance, port_load = chokes[0]
        leg, fraction, _, _ = locate(legs, port_distance)
        port = (wires[leg], fraction)
    else:
        port, port_distance, port_load = (wires[0], 0.0), 0.0, None

    earth = None
    fl = project.feedline
    radio = legs[-1].p2
    if fl["radio_end"] == "earthed" and project.environment["ground"] != "free_space" \
            and radio[2] > EPS:
        earth = model.add_wire(Wire(radio, (radio[0], radio[1], 0.0), EARTH_LEAD_RADIUS,
                                    "Earth lead", part_id=NODE_FEEDLINE))
        if fl["earth_resistance"] > 0:
            model.loads.append(Load(earth, 1.0, r_ohm=fl["earth_resistance"], kind=SERIES,
                                    name="Earth connection", part_id=NODE_FEEDLINE))
    return ShieldInfo(wires, earth, total, port, port_distance, port_load, chokes)


# ---- checks ------------------------------------------------------------------


def validate(project: "Project") -> list[Issue]:
    fl = project.feedline
    if not fl["common_mode"]:
        return []
    issues: list[Issue] = []
    coax = coax_type(project)
    template = project.template
    if coax is None:
        issues.append(Issue(ERROR, "Choose a coax type under Feed system to model its shield.",
                            NODE_FEEDLINE))
        return issues
    if coax.shield_diameter_m is None:
        issues.append(Issue(ERROR, f"{coax.label} is balanced and has no shield; common mode "
                                   f"is only modelled for coax.", NODE_FEEDLINE))
        return issues
    if template.feed_point(project) is None:
        issues.append(Issue(INFO, f"Common mode is not modelled for the {template.name}.",
                            NODE_FEEDLINE))
        return issues
    if template.feed_is_grounded(project):
        issues.append(Issue(INFO, "The feed is at ground level, where the shield is bonded to "
                                  "the ground system, so common mode is not modelled.",
                            NODE_FEEDLINE))
        return issues
    if fl["radio_end"] == "earthed" and project.environment["ground"] == "free_space":
        issues.append(Issue(ERROR, "An earthed radio needs a ground; pick a ground or a "
                                   "floating radio.", NODE_FEEDLINE))

    total = route_length(project)
    design = project.simulation["design_mhz"]
    for choke in project.parts_of("choke"):
        label = project.part_label(choke)
        if choke.params["distance"] > total + EPS:
            issues.append(Issue(WARNING, f"{label} sits beyond the end of the coax "
                                         f"({total:.2f} m); it has been placed at the radio.",
                                choke.id))
        coil = choke_model(project, choke)
        if coil is None:
            continue
        z = coil.impedance(design)
        srf = coil.self_resonance_mhz
        kind = "inductive" if z.imag >= 0 else "capacitive"
        issues.append(Issue(INFO, f"{label}: {coil.inductance_uh:.1f} µH with about "
                                  f"{coil.capacitance_pf:.1f} pF self-capacitance, self-resonant "
                                  f"near {srf:.1f} MHz. At {design:g} MHz: |Z| = "
                                  f"{abs(z):.0f} Ω, {kind}.", choke.id))
        if design > srf:
            issues.append(Issue(WARNING, f"{label} is above its self-resonance at {design:g} "
                                         f"MHz, so it acts as a capacitor and chokes poorly. "
                                         f"Use fewer turns or a smaller form.", choke.id))
        elif design > 0.8 * srf:
            issues.append(Issue(WARNING, f"{label} is close to self-resonance. Coax windings "
                                         f"have more capacitance than this estimate, so the "
                                         f"real choke may already be past it. Measure it, or "
                                         f"use fewer turns.", choke.id))
    return issues


# ---- diagram -----------------------------------------------------------------


def handles(project: "Project") -> list[Handle]:
    if not is_modelled(project):
        return []
    legs = route(project)
    out: list[Handle] = []
    for leg in legs:
        if leg.part_id == NODE_FEEDLINE or leg.length < EPS:
            continue
        u = tuple((leg.p2[k] - leg.p1[k]) / leg.length for k in range(3))
        for view in (SIDE, TOP):
            h = along_handle(view, leg.part_id, "length", leg.p2, u, leg.length, "Coax run length")
            if h is not None:
                out.append(h)
    if legs:
        radio = legs[-1].p2
        out.append(Handle(SIDE, NODE_FEEDLINE, "radio_height", (radio[0], radio[2]), (0.0, 1.0),
                          project.feedline["radio_height"], "Radio height"))
        total = sum(leg.length for leg in legs)
        for choke in project.parts_of("choke"):
            along = min(choke.params["distance"], total)
            _, _, point, u = locate(legs, along)
            for view in (SIDE, TOP):
                h = along_handle(view, choke.id, "distance", point, u, along, "Choke position")
                if h is not None:
                    out.append(h)
    return out


def choke_points(project: "Project") -> list[tuple[str, Vec3]]:
    if not is_modelled(project):
        return []
    legs = route(project)
    if not legs:
        return []
    total = sum(leg.length for leg in legs)
    return [(c.id, locate(legs, min(c.params["distance"], total))[2])
            for c in project.parts_of("choke")]


# ---- build outputs -------------------------------------------------------------


def cut_items(project: "Project") -> list[CutItem]:
    if not is_modelled(project):
        return []
    coax = coax_type(project)
    fl = project.feedline
    items = []
    wound = False
    for choke in project.parts_of("choke"):
        coil = choke_model(project, choke)
        if coil is None:
            continue
        wound = True
        items.append(CutItem(f"Choke ({project.part_label(choke)})", 1, coil.coax_length_m,
                             f"{coil.turns} turns of {coax.label} close wound on a "
                             f"Ø {choke.params['form_diameter'] * 1000:.0f} mm form, "
                             f"{coil.inductance_uh:.1f} µH"))
    note = f"{coax.label}, modelled route"
    if fl["extra_length"] > 0:
        note += f" plus {fl['extra_length']:.2f} m extra at the radio"
    if wound:
        note += ", plus the choke windings"
    items.insert(0, CutItem("Coax", 1, feedline_length(project), note))
    return items
