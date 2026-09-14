"""Monopole / vertical family: ground-mounted or elevated verticals, inverted L
(L hang), with radials, capacitive top hat and loading coil."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..geometry.validation import ERROR, INFO, WARNING, Issue
from ..geometry.wire_model import Load, Source, Wire, WireModel
from ..model.document import NODE_ANTENNA, NODE_ENVIRONMENT
from ..model.params import ParamSpec
from .base import (SIDE, TOP, AntennaTemplate, BuildContext, CutItem, Decoration, Dimension, Handle,
                   Tunable)

if TYPE_CHECKING:
    from ..model.document import Project

_EPS = 1e-6


def _polar(length: float, azimuth_deg: float, droop_deg: float, origin):
    az, dr = math.radians(azimuth_deg), math.radians(droop_deg)
    horiz = length * math.cos(dr)
    return (origin[0] + horiz * math.cos(az),
            origin[1] + horiz * math.sin(az),
            origin[2] - length * math.sin(dr))


class MonopoleTemplate(AntennaTemplate):
    id = "monopole"
    name = "Monopole / vertical"
    description = ("Vertical radiator fed against ground or radials. Add a horizontal "
                   "section for an inverted L / L hang.")
    allowed_parts = ("radials", "top_hat", "loading_coil")
    specs = (
        ParamSpec("height", "Vertical length", "length", 5.0, minimum=0.05),
        ParamSpec("diameter", "Element diameter", "small_length", 20e-3, minimum=1e-5),
        ParamSpec("feed_height", "Feed height above ground", "length", 3.0, minimum=0.0,
                  help="0 means ground-mounted. Over real ground a ground-mounted "
                       "vertical uses buried radials or a ground-loss estimate."),
        ParamSpec("top_length", "Horizontal section (L)", "length", 0.0, minimum=0.0,
                  help="Length of the wire running from the top of the vertical. "
                       "0 = plain vertical, >0 = inverted L / L hang."),
        ParamSpec("top_azimuth", "Horizontal section direction", "angle", 0.0,
                  minimum=0.0, maximum=360.0),
        ParamSpec("top_slope", "Horizontal section slope", "angle", 0.0,
                  minimum=-80.0, maximum=80.0,
                  help="0° is horizontal, positive slopes downward."),
    )

    def apply_defaults(self, project: "Project") -> None:
        # 45° offset keeps radials from hiding behind the element in the side view.
        project.add_part("radials", {"mode": "wires", "count": 4, "length": 5.1, "droop": 30.0,
                                     "azimuth": 45.0})

    # ---- geometry -------------------------------------------------------

    def _points(self, project: "Project"):
        a = project.antenna
        base = (0.0, 0.0, a["feed_height"])
        top = (0.0, 0.0, a["feed_height"] + a["height"])
        return a, base, top

    def feed_is_grounded(self, project: "Project") -> bool:
        return project.antenna["feed_height"] <= _EPS and project.environment["ground"] != "free_space"

    def build(self, project: "Project", ctx: BuildContext) -> WireModel:
        a, base, top = self._points(project)
        model = WireModel()
        radius = a["diameter"] / 2
        height = a["height"]

        # Split the vertical where a loading coil sits; the coil is a short
        # single-segment wire carrying the RLC load.
        coil = project.first_part("loading_coil")
        cuts: list[tuple[float, float]] = []
        if coil is not None:
            coil_len = min(ctx.segment_length, height / 3)
            z0 = min(max(coil.params["height"] - coil_len / 2, 0.0), height - coil_len)
            cuts.append((z0, z0 + coil_len))

        z = 0.0
        sections: list[tuple[float, float, bool]] = []
        for c0, c1 in cuts:
            if c0 - z > _EPS:
                sections.append((z, c0, False))
            sections.append((c0, c1, True))
            z = c1
        if height - z > _EPS:
            sections.append((z, height, False))

        first_vertical = None
        for z0, z1, is_coil in sections:
            wire = Wire((0.0, 0.0, base[2] + z0), (0.0, 0.0, base[2] + z1), radius,
                        "Loading coil" if is_coil else "Vertical element",
                        part_id=coil.id if is_coil else NODE_ANTENNA,
                        segments=1 if is_coil else 0)
            idx = model.add_wire(wire)
            if first_vertical is None:
                first_vertical = idx
            if is_coil:
                model.loads.append(Load(idx, 0.5, l_uh=coil.params["inductance"],
                                        q=coil.params["q"], name="Loading coil",
                                        part_id=coil.id))
        model.source = Source(first_vertical, 0.0)

        if a["top_length"] > _EPS:
            end = _polar(a["top_length"], a["top_azimuth"], a["top_slope"], top)
            model.add_wire(Wire(top, end, radius, "Horizontal section"))

        hat = project.first_part("top_hat")
        if hat is not None:
            p = hat.params
            r_hat = p["diameter"] / 2
            tips = [_polar(p["length"], 360.0 * i / p["spokes"], p["droop"], top)
                    for i in range(p["spokes"])]
            for i, tip in enumerate(tips):
                model.add_wire(Wire(top, tip, r_hat, f"Top hat spoke {i + 1}", part_id=hat.id))
            if p["ring"] and p["spokes"] >= 3:
                for i, tip in enumerate(tips):
                    model.add_wire(Wire(tip, tips[(i + 1) % len(tips)], r_hat,
                                        f"Top hat ring {i + 1}", part_id=hat.id))

        radials = project.first_part("radials")
        if radials is not None and radials.params["mode"] == "wires":
            p = radials.params
            r_rad = p["diameter"] / 2
            for i in range(p["count"]):
                tip = _polar(p["length"], p["azimuth"] + 360.0 * i / p["count"], p["droop"], base)
                model.add_wire(Wire(base, tip, r_rad, f"Radial {i + 1}", part_id=radials.id))
        return model

    # ---- validation ----------------------------------------------------

    def validate(self, project: "Project") -> list[Issue]:
        issues: list[Issue] = []
        a = project.antenna
        ground = project.environment["ground"]
        radials = project.first_part("radials")
        wire_radials = radials is not None and radials.params["mode"] == "wires"
        buried = radials is not None and radials.params["mode"] == "buried"
        grounded_feed = a["feed_height"] <= _EPS

        if ground == "free_space" and not wire_radials:
            issues.append(Issue(ERROR, "In free space a monopole needs modeled radials "
                                       "(a counterpoise) to feed against.", NODE_ENVIRONMENT))
        if ground != "free_space" and not grounded_feed and not wire_radials:
            issues.append(Issue(ERROR, "An elevated feed point needs modeled radials to feed "
                                       "against. Set feed height to 0 or add radials.", NODE_ANTENNA))
        if buried and not grounded_feed:
            issues.append(Issue(ERROR, "Buried radials require a feed height of 0.", radials.id))
        if buried and ground == "free_space":
            issues.append(Issue(ERROR, "Buried radials need a ground.", radials.id))
        if buried and ground == "perfect":
            issues.append(Issue(INFO, "Buried radials have no effect over perfect ground.", radials.id))
        if wire_radials and grounded_feed and ground != "free_space":
            issues.append(Issue(ERROR, "Modeled radials at feed height 0 would lie on the ground. "
                                       "Raise the feed point or switch radials to "
                                       "'On / in ground'.", radials.id))
        if wire_radials:
            p = radials.params
            tip_z = a["feed_height"] - p["length"] * math.sin(math.radians(p["droop"]))
            if ground != "free_space" and tip_z < 0 and not grounded_feed:
                issues.append(Issue(ERROR, "Radial tips go below ground; reduce droop or "
                                           "raise the feed point.", radials.id))
        coil = project.first_part("loading_coil")
        if coil is not None and coil.params["height"] > a["height"]:
            issues.append(Issue(WARNING, "Loading coil position is above the top of the "
                                         "element; it has been clamped.", coil.id))
        top_end_z = (a["feed_height"] + a["height"]
                     - a["top_length"] * math.sin(math.radians(a["top_slope"])))
        if ground != "free_space" and a["top_length"] > _EPS and top_end_z < 0:
            issues.append(Issue(ERROR, "The horizontal section slopes below ground.", NODE_ANTENNA))
        return issues

    # ---- diagram ---------------------------------------------------------

    def handles(self, project: "Project") -> list[Handle]:
        a, base, top = self._points(project)
        out = [
            Handle(SIDE, NODE_ANTENNA, "height", (0.0, top[2]), (0.0, 1.0), a["height"],
                   "Vertical length"),
            Handle(SIDE, NODE_ANTENNA, "feed_height", (0.0, base[2]), (0.0, 1.0),
                   a["feed_height"], "Feed height"),
        ]
        az = math.radians(a["top_azimuth"])
        slope = math.radians(a["top_slope"])
        end = _polar(max(a["top_length"], 0.0), a["top_azimuth"], a["top_slope"], top)
        horiz = math.cos(slope)
        if abs(math.cos(az)) * horiz > 0.2:
            ux, uz = math.cos(az) * horiz, -math.sin(slope)
            norm = ux * ux + uz * uz
            out.append(Handle(SIDE, NODE_ANTENNA, "top_length", (end[0], end[2]),
                              (ux / norm, uz / norm), a["top_length"], "Horizontal section"))
        if horiz > 0.2:
            out.append(Handle(TOP, NODE_ANTENNA, "top_length", (end[0], end[1]),
                              (math.cos(az) / horiz, math.sin(az) / horiz),
                              a["top_length"], "Horizontal section"))

        coil = project.first_part("loading_coil")
        if coil is not None:
            h = min(coil.params["height"], a["height"])
            out.append(Handle(SIDE, coil.id, "height", (0.0, base[2] + h), (0.0, 1.0), h,
                              "Coil position"))

        hat = project.first_part("top_hat")
        if hat is not None:
            p = hat.params
            dr = math.radians(p["droop"])
            tip = _polar(p["length"], 0.0, p["droop"], top)
            ux, uz = math.cos(dr), -math.sin(dr)
            out.append(Handle(SIDE, hat.id, "length", (tip[0], tip[2]), (ux, uz), p["length"],
                              "Top hat spoke"))

        radials = project.first_part("radials")
        if radials is not None:
            p = radials.params
            droop = p["droop"] if p["mode"] == "wires" else 0.0
            az_r = p["azimuth"] if p["mode"] == "wires" else 0.0
            tip = _polar(p["length"], az_r, droop, base)
            dr, azr = math.radians(droop), math.radians(az_r)
            out.append(Handle(TOP, radials.id, "length", (tip[0], tip[1]),
                              (math.cos(azr) / math.cos(dr), math.sin(azr) / math.cos(dr)),
                              p["length"], "Radial length"))
            if abs(math.cos(azr)) > 0.2:
                ux, uz = math.cos(azr) * math.cos(dr), -math.sin(dr)
                norm = ux * ux + uz * uz
                out.append(Handle(SIDE, radials.id, "length", (tip[0], tip[2]),
                                  (ux / norm, uz / norm), p["length"], "Radial length"))
        return out

    def decorations(self, project: "Project") -> list[Decoration]:
        radials = project.first_part("radials")
        if radials is None or radials.params["mode"] != "buried":
            return []
        p = radials.params
        out = []
        for i in range(p["count"]):
            az = math.radians(360.0 * i / p["count"])
            x, y = p["length"] * math.cos(az), p["length"] * math.sin(az)
            out.append(Decoration(TOP, (0.0, 0.0), (x, y), radials.id))
            if abs(math.cos(az)) > 1e-6:
                out.append(Decoration(SIDE, (0.0, 0.0), (x, 0.0), radials.id))
        return out

    def dimensions(self, project: "Project") -> list[Dimension]:
        a, base, top = self._points(project)
        dims = [Dimension(SIDE, (0.0, base[2]), (0.0, top[2]), a["height"], "L", 45)]
        if a["feed_height"] > _EPS:
            dims.append(Dimension(SIDE, (0.0, 0.0), (0.0, base[2]), a["feed_height"], "h", -45))
        if a["top_length"] > _EPS:
            end = _polar(a["top_length"], a["top_azimuth"], a["top_slope"], top)
            dims.append(Dimension(TOP, (0.0, 0.0), (end[0], end[1]), a["top_length"], "L₂", 25))
        radials = project.first_part("radials")
        if radials is not None:
            p = radials.params
            droop = p["droop"] if p["mode"] == "wires" else 0.0
            az_r = p["azimuth"] if p["mode"] == "wires" else 0.0
            tip = _polar(p["length"], az_r, droop, base)
            dims.append(Dimension(TOP, (0.0, 0.0), (tip[0], tip[1]), p["length"], "r", -25))
        return dims

    # ---- build outputs --------------------------------------------------

    def cut_list(self, project: "Project") -> list[CutItem]:
        a = project.antenna
        items = [CutItem("Vertical element", 1, a["height"],
                         f"Ø {a['diameter'] * 1000:.1f} mm")]
        if a["top_length"] > _EPS:
            items.append(CutItem("Horizontal section", 1, a["top_length"]))
        hat = project.first_part("top_hat")
        if hat is not None:
            p = hat.params
            items.append(CutItem("Top hat spoke", p["spokes"], p["length"]))
            if p["ring"] and p["spokes"] >= 3:
                chord = 2 * p["length"] * math.cos(math.radians(p["droop"])) * math.sin(math.pi / p["spokes"])
                items.append(CutItem("Top hat ring", 1, chord * p["spokes"],
                                     f"{p['spokes']} equal sides"))
        radials = project.first_part("radials")
        if radials is not None:
            p = radials.params
            items.append(CutItem("Radial", p["count"], p["length"],
                                 "buried / on ground" if p["mode"] == "buried" else ""))
        coil = project.first_part("loading_coil")
        if coil is not None:
            items.append(CutItem("Loading coil", 1, 0.0,
                                 f"{coil.params['inductance']:.2f} µH, see coil calculator"))
        return items

    def tunables(self, project: "Project") -> list[Tunable]:
        a = project.antenna
        out = [Tunable(NODE_ANTENNA, "height", "Vertical length", 0.1, max(a["height"] * 3, 1.0))]
        if a["top_length"] > _EPS:
            out.append(Tunable(NODE_ANTENNA, "top_length", "Horizontal section", 0.0,
                               max(a["top_length"] * 3, 1.0)))
        coil = project.first_part("loading_coil")
        if coil is not None:
            out.append(Tunable(coil.id, "inductance", "Coil inductance", 0.0,
                               max(coil.params["inductance"] * 5, 50.0)))
        hat = project.first_part("top_hat")
        if hat is not None:
            out.append(Tunable(hat.id, "length", "Top hat spoke length", 0.05,
                               max(hat.params["length"] * 3, 1.0)))
        radials = project.first_part("radials")
        if radials is not None and radials.params["mode"] == "wires":
            out.append(Tunable(radials.id, "length", "Radial length", 0.1,
                               max(radials.params["length"] * 3, 1.0)))
        return out
