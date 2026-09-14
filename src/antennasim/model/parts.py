"""Specs for the add-on parts and the fixed project nodes."""

from __future__ import annotations

from dataclasses import dataclass

from .materials import COAX, CONDUCTORS, GROUNDS
from .params import ParamSpec


@dataclass(frozen=True)
class PartType:
    kind: str
    label: str
    specs: tuple[ParamSpec, ...]
    max_count: int = 1


RADIALS = PartType(
    "radials",
    "Radials",
    (
        ParamSpec("mode", "Type", "choice", "wires",
                  choices=(("wires", "Modeled wires (elevated)"),
                           ("buried", "On / in ground (loss estimate)")),
                  help="NEC2 cannot model wires in or on real ground. Buried radials "
                       "are represented by an estimated ground-loss resistance."),
        ParamSpec("count", "Count", "int", 4, minimum=1, maximum=120),
        ParamSpec("length", "Length", "length", 5.0, minimum=0.05),
        ParamSpec("droop", "Droop angle", "angle", 0.0, minimum=-60.0, maximum=80.0,
                  help="0° is horizontal, positive slopes the radials downward.",
                  visible_when=("mode", ("wires",))),
        ParamSpec("azimuth", "Azimuth offset", "angle", 0.0, minimum=0.0, maximum=360.0,
                  visible_when=("mode", ("wires",))),
        ParamSpec("diameter", "Wire diameter", "small_length", 2.0e-3, minimum=1e-5,
                  visible_when=("mode", ("wires",))),
    ),
)

TOP_HAT = PartType(
    "top_hat",
    "Capacitive top hat",
    (
        ParamSpec("spokes", "Spokes", "int", 4, minimum=2, maximum=16),
        ParamSpec("length", "Spoke length", "length", 1.0, minimum=0.05),
        ParamSpec("droop", "Droop angle", "angle", 0.0, minimum=-45.0, maximum=60.0,
                  help="0° is horizontal, positive slopes the spokes downward."),
        ParamSpec("ring", "Perimeter ring", "bool", True),
        ParamSpec("diameter", "Wire diameter", "small_length", 2.0e-3, minimum=1e-5),
    ),
)

LOADING_COIL = PartType(
    "loading_coil",
    "Loading coil",
    (
        ParamSpec("height", "Position above feed", "length", 0.0, minimum=0.0,
                  help="Distance along the vertical element from the feed point."),
        ParamSpec("inductance", "Inductance", "inductance", 10.0, minimum=0.0),
        ParamSpec("q", "Coil Q", "float", 200.0, minimum=1.0, maximum=5000.0,
                  help="Unloaded Q. Loss resistance is X_L / Q at each frequency."),
    ),
)

PART_TYPES: dict[str, PartType] = {p.kind: p for p in (RADIALS, TOP_HAT, LOADING_COIL)}


ENVIRONMENT_SPECS = (
    ParamSpec("ground", "Ground", "choice", "real",
              choices=(("free_space", "Free space"),
                       ("perfect", "Perfect ground"),
                       ("real", "Real ground"))),
    ParamSpec("soil", "Soil", "choice", "average",
              choices=tuple((k, g.label) for k, g in GROUNDS.items()),
              visible_when=("ground", ("real",))),
    ParamSpec("ground_loss", "Ground loss", "choice", "estimate",
              choices=(("estimate", "Estimate from radials"),
                       ("manual", "Manual")),
              help="Series loss resistance for ground-mounted verticals.",
              visible_when=("ground", ("real",))),
    ParamSpec("ground_loss_ohms", "Ground loss resistance", "resistance", 10.0,
              minimum=0.0, visible_when=("ground_loss", ("manual",))),
    ParamSpec("conductor", "Wire material", "choice", "copper",
              choices=tuple((k, v[0]) for k, v in CONDUCTORS.items())),
)

FEEDLINE_SPECS = (
    ParamSpec("z0", "Reference impedance", "resistance", 50.0, minimum=1.0,
              help="Impedance SWR is calculated against (your radio / feedline)."),
    ParamSpec("transformer_ratio", "Balun / unun ratio", "float", 1.0,
              minimum=0.01, maximum=100.0,
              help="Impedance ratio antenna:line. 9 means a 9:1 unun."),
    ParamSpec("coax", "Feedline", "choice", "rg213",
              choices=(("none", "None"),) + tuple((k, c.label) for k, c in COAX.items())),
    ParamSpec("length", "Feedline length", "length", 20.0, minimum=0.0,
              visible_when=("coax", tuple(COAX))),
)

SIMULATION_SPECS = (
    ParamSpec("design_mhz", "Design frequency", "frequency", 14.2, minimum=0.1, maximum=3000.0),
    ParamSpec("sweep_start", "Sweep start", "frequency", 13.5, minimum=0.1, maximum=3000.0),
    ParamSpec("sweep_stop", "Sweep stop", "frequency", 15.0, minimum=0.1, maximum=3000.0),
    ParamSpec("sweep_points", "Sweep points", "int", 31, minimum=2, maximum=401),
    ParamSpec("segments_per_wavelength", "Segments per wavelength", "int", 20,
              minimum=10, maximum=100,
              help="Higher is more accurate and slower. 20 is a good default."),
    ParamSpec("swr_threshold", "SWR bandwidth threshold", "float", 2.0,
              minimum=1.1, maximum=10.0),
)
