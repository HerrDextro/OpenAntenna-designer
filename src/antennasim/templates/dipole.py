"""Dipole family: flat, inverted V, sloping and vertical dipoles, with symmetric
loading coils."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..geometry.validation import ERROR, WARNING, Issue
from ..geometry.wire_model import Source, WireModel
from ..model.document import NODE_ANTENNA
from ..model.params import ParamSpec
from ..model.units import wavelength_m
from .base import (EPS, SIDE, TOP, AntennaTemplate, BuildContext, CutItem, Dimension, Handle,
                   Tunable, add_run, max_coil_uh, polar_point)

if TYPE_CHECKING:
    from ..model.document import Project


class DipoleTemplate(AntennaTemplate):
    id = "dipole"
    name = "Dipole"
    description = ("Centre-fed dipole: flat, inverted V, sloping or vertical. Add loading "
                   "coils to shorten it.")
    allowed_parts = ("loading_coil",)
    specs = (
        ParamSpec("leg_length", "Leg length (each side)", "length", 5.05, minimum=0.05,
                  help="Half the total length. A half-wave dipole is about λ/4 per leg."),
        ParamSpec("diameter", "Wire diameter", "small_length", 2e-3, minimum=1e-5),
        ParamSpec("height", "Feed height above ground", "length", 10.0, minimum=0.0,
                  help="Height of the feed point: the apex of an inverted V, or the "
                       "centre of a vertical dipole."),
        ParamSpec("tilt", "Tilt from horizontal", "angle", 0.0, minimum=0.0, maximum=90.0,
                  help="0° is horizontal, 90° is a vertical dipole, in between is a "
                       "sloper. Leg 1 is the upper leg."),
        ParamSpec("droop", "Leg droop", "angle", 0.0, minimum=-85.0, maximum=85.0,
                  help="0° is a flat dipole; positive slopes both legs down (inverted V), "
                       "negative slopes them up."),
        ParamSpec("azimuth", "Direction", "angle", 0.0, minimum=0.0, maximum=360.0,
                  help="Compass direction the wire runs. Radiation is broadside to this."),
    )

    # ---- geometry -------------------------------------------------------

    def _points(self, project: "Project"):
        """Feed point and leg tips.

        Both legs lie in the vertical plane through `azimuth`. Tilt raises leg 1
        and lowers leg 2 by the same angle; droop then bends each leg further
        toward the ground. With tilt 0 this is the familiar flat / inverted V
        dipole, with tilt 90 it stands vertical.
        """
        a = project.antenna
        feed = (0.0, 0.0, a["height"])
        tip_a = polar_point(a["leg_length"], a["azimuth"], a["droop"] - a["tilt"], feed)
        tip_b = polar_point(a["leg_length"], a["azimuth"] + 180.0, a["droop"] + a["tilt"], feed)
        return a, feed, tip_a, tip_b

    @staticmethod
    def _direction(feed, tip, length: float):
        return tuple((tip[i] - feed[i]) / length for i in range(3))

    def build(self, project: "Project", ctx: BuildContext) -> WireModel:
        a, feed, tip_a, tip_b = self._points(project)
        model = WireModel()
        radius = a["diameter"] / 2
        coil = project.first_part("loading_coil")
        distance = coil.params["height"] if coil else 0.0

        # Each leg is its own run so an inverted V and its coils stay symmetric.
        first = add_run(model, feed, tip_a, radius, "Leg 1", ctx, NODE_ANTENNA, coil, distance)
        add_run(model, feed, tip_b, radius, "Leg 2", ctx, NODE_ANTENNA, coil, distance)
        model.source = Source(first, 0.0)
        return model

    # ---- validation ----------------------------------------------------

    def validate(self, project: "Project") -> list[Issue]:
        a, feed, tip_a, tip_b = self._points(project)
        issues: list[Issue] = []
        ground = project.environment["ground"]
        lowest = min(tip_a[2], tip_b[2], feed[2])
        if ground != "free_space":
            if lowest < 0:
                issues.append(Issue(ERROR, "A leg end goes below ground; reduce the droop or "
                                           "tilt, or raise the feed point.", NODE_ANTENNA))
            elif lowest < 0.5:
                issues.append(Issue(WARNING, "The antenna is very close to the ground; NEC2 "
                                             "results are unreliable there.", NODE_ANTENNA))
            lam = wavelength_m(project.simulation["design_mhz"])
            # A low horizontal dipole fires upward; a vertical one does not.
            if a["tilt"] < 45 and 0 <= feed[2] < 0.15 * lam:
                issues.append(Issue(WARNING, f"The feed point is under 0.15 λ "
                                             f"({0.15 * lam:.1f} m) up. Expect a low feed "
                                             f"impedance and a high take-off angle.",
                                    NODE_ANTENNA))
        coil = project.first_part("loading_coil")
        if coil is not None and coil.params["height"] > a["leg_length"]:
            issues.append(Issue(WARNING, "The loading coils sit beyond the end of the legs; "
                                         "the position has been clamped.", coil.id))
        return issues

    # ---- diagram ---------------------------------------------------------

    def handles(self, project: "Project") -> list[Handle]:
        a, feed, tip_a, tip_b = self._points(project)
        length = a["leg_length"]
        dir_a = self._direction(feed, tip_a, length)
        dir_b = self._direction(feed, tip_b, length)
        out = [Handle(SIDE, NODE_ANTENNA, "height", (0.0, feed[2]), (0.0, 1.0), a["height"],
                      "Feed height")]
        for view in (SIDE, TOP):
            for tip, direction in ((tip_a, dir_a), (tip_b, dir_b)):
                handle = _along(view, NODE_ANTENNA, "leg_length", tip, direction, length,
                                "Leg length")
                if handle is not None:
                    out.append(handle)
        coil = project.first_part("loading_coil")
        if coil is not None:
            d = min(coil.params["height"], length)
            pos = tuple(feed[i] + dir_a[i] * d for i in range(3))
            for view in (SIDE, TOP):
                handle = _along(view, coil.id, "height", pos, dir_a, d, "Coil position")
                if handle is not None:
                    out.append(handle)
        return out

    def dimensions(self, project: "Project") -> list[Dimension]:
        a, feed, tip_a, tip_b = self._points(project)
        # Dimension the full span in whichever view shows it longer.
        side_span = math.hypot(tip_a[0] - tip_b[0], tip_a[2] - tip_b[2])
        top_span = math.hypot(tip_a[0] - tip_b[0], tip_a[1] - tip_b[1])
        if side_span > top_span:
            dims = [Dimension(SIDE, (tip_b[0], tip_b[2]), (tip_a[0], tip_a[2]),
                              2 * a["leg_length"], "total", 30)]
        else:
            dims = [Dimension(TOP, (tip_b[0], tip_b[1]), (tip_a[0], tip_a[1]),
                              2 * a["leg_length"], "total", 30)]
        if project.environment["ground"] != "free_space":
            dims.append(Dimension(SIDE, (0.0, 0.0), (0.0, feed[2]), a["height"], "h", -45))
        if abs(a["droop"]) > EPS:
            dims.append(Dimension(SIDE, (0.0, feed[2]), (tip_a[0], tip_a[2]), a["leg_length"],
                                  "L", 30))
        return dims

    # ---- build outputs --------------------------------------------------

    def cut_list(self, project: "Project") -> list[CutItem]:
        a = project.antenna
        items = [CutItem("Dipole leg", 2, a["leg_length"],
                         f"Ø {a['diameter'] * 1000:.1f} mm, {2 * a['leg_length']:.3f} m total")]
        coil = project.first_part("loading_coil")
        if coil is not None:
            items.append(CutItem("Loading coil", 2, 0.0,
                                 f"{coil.params['inductance']:.2f} µH each, one per leg"))
        return items

    def tunables(self, project: "Project") -> list[Tunable]:
        # Legs beyond ~0.45 λ approach the full-wave antiresonance; stay below it
        # so tuning finds the half-wave (fundamental) resonance.
        lam = wavelength_m(project.simulation["design_mhz"])
        out = [Tunable(NODE_ANTENNA, "leg_length", "Leg length", 0.01 * lam, 0.45 * lam)]
        coil = project.first_part("loading_coil")
        if coil is not None:
            out.append(Tunable(coil.id, "inductance", "Coil inductance", 0.0,
                               max_coil_uh(project.simulation["design_mhz"])))
        return out


def _along(view: str, node_id: str, key: str, pos, direction, value: float,
           label: str) -> Handle | None:
    """Handle at `pos` that edits a length measured along `direction`.

    Moving the handle by t along the leg's projection changes the value by t,
    so the axis is the projected direction divided by its squared length. A
    leg pointing almost straight at the viewer gets no handle in that view.
    """
    if view == SIDE:
        dx, dy, at = direction[0], direction[2], (pos[0], pos[2])
    else:
        dx, dy, at = direction[0], direction[1], (pos[0], pos[1])
    norm = dx * dx + dy * dy
    if norm < 0.04:
        return None
    return Handle(view, node_id, key, at, (dx / norm, dy / norm), value, label)
