"""Dipole family: flat dipole, inverted V and sloper, with symmetric loading coils."""

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
    description = ("Centre-fed dipole. Droop the legs for an inverted V, or add loading "
                   "coils to shorten it.")
    allowed_parts = ("loading_coil",)
    specs = (
        ParamSpec("leg_length", "Leg length (each side)", "length", 5.05, minimum=0.05,
                  help="Half the total length. A half-wave dipole is about λ/4 per leg."),
        ParamSpec("diameter", "Wire diameter", "small_length", 2e-3, minimum=1e-5),
        ParamSpec("height", "Feed height above ground", "length", 10.0, minimum=0.0,
                  help="Height of the feed point, i.e. the apex of an inverted V."),
        ParamSpec("droop", "Leg droop", "angle", 0.0, minimum=-85.0, maximum=85.0,
                  help="0° is a flat dipole; positive slopes both legs down (inverted V), "
                       "negative slopes them up."),
        ParamSpec("azimuth", "Direction", "angle", 0.0, minimum=0.0, maximum=360.0,
                  help="Compass direction the wire runs. Radiation is broadside to this."),
    )

    # ---- geometry -------------------------------------------------------

    def _points(self, project: "Project"):
        a = project.antenna
        feed = (0.0, 0.0, a["height"])
        tip_a = polar_point(a["leg_length"], a["azimuth"], a["droop"], feed)
        tip_b = polar_point(a["leg_length"], a["azimuth"] + 180.0, a["droop"], feed)
        return a, feed, tip_a, tip_b

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
                issues.append(Issue(ERROR, "The leg ends go below ground; reduce the droop or "
                                           "raise the feed point.", NODE_ANTENNA))
            elif lowest < 0.5:
                issues.append(Issue(WARNING, "The antenna is very close to the ground; NEC2 "
                                             "results are unreliable there.", NODE_ANTENNA))
            lam = wavelength_m(project.simulation["design_mhz"])
            if 0 <= feed[2] < 0.15 * lam:
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
        az, dr = math.radians(a["azimuth"]), math.radians(a["droop"])
        out = [Handle(SIDE, NODE_ANTENNA, "height", (0.0, feed[2]), (0.0, 1.0), a["height"],
                      "Feed height")]
        horiz = math.cos(dr)
        for tip, sign in ((tip_a, 1.0), (tip_b, -1.0)):
            ux, uz = sign * math.cos(az) * horiz, -math.sin(dr)
            norm = ux * ux + uz * uz
            if abs(ux) > 0.2 and norm > 0:
                out.append(Handle(SIDE, NODE_ANTENNA, "leg_length", (tip[0], tip[2]),
                                  (ux / norm, uz / norm), a["leg_length"], "Leg length"))
            if horiz > 0.2:
                out.append(Handle(TOP, NODE_ANTENNA, "leg_length", (tip[0], tip[1]),
                                  (sign * math.cos(az) / horiz, sign * math.sin(az) / horiz),
                                  a["leg_length"], "Leg length"))
        coil = project.first_part("loading_coil")
        if coil is not None:
            d = min(coil.params["height"], a["leg_length"])
            pos = polar_point(d, a["azimuth"], a["droop"], feed)
            if horiz > 0.2:
                out.append(Handle(TOP, coil.id, "height", (pos[0], pos[1]),
                                  (math.cos(az) / horiz, math.sin(az) / horiz), d,
                                  "Coil position"))
        return out

    def dimensions(self, project: "Project") -> list[Dimension]:
        a, feed, tip_a, tip_b = self._points(project)
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
