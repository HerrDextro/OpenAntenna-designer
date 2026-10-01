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
        ParamSpec("droop", "Droop angle", "angle", 0.0, minimum=-85.0, maximum=85.0,
                  help="0° is horizontal, positive slopes the radials downward, "
                       "negative slopes them upward.",
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
        ParamSpec("droop", "Droop angle", "angle", 0.0, minimum=-85.0, maximum=85.0,
                  help="0° is horizontal, positive slopes the spokes downward, "
                       "negative slopes them upward."),
        ParamSpec("ring", "Perimeter ring", "bool", True),
        ParamSpec("diameter", "Wire diameter", "small_length", 2.0e-3, minimum=1e-5),
    ),
)

LOADING_COIL = PartType(
    "loading_coil",
    "Loading coil",
    (
        ParamSpec("height", "Distance from feed", "length", 0.0, minimum=0.0,
                  help="Distance along the element from the feed point. On a dipole a coil "
                       "is placed on each leg at this distance."),
        ParamSpec("inductance", "Inductance", "inductance", 10.0, minimum=0.0),
        ParamSpec("q", "Coil Q", "float", 200.0, minimum=1.0, maximum=5000.0,
                  help="Unloaded Q. Loss resistance is X_L / Q at each frequency."),
    ),
)

COAX_RUN = PartType(
    "coax_run",
    "Coax run",
    (
        ParamSpec("length", "Length", "length", 1.0, minimum=0.01),
        ParamSpec("azimuth", "Direction", "angle", 0.0, minimum=0.0, maximum=360.0,
                  help="Compass direction of this run, seen from above."),
        ParamSpec("slope", "Slope", "angle", 0.0, minimum=-90.0, maximum=90.0,
                  help="0° is horizontal, 90° runs straight down, negative values climb."),
    ),
    max_count=12,
)

CHOKE = PartType(
    "choke",
    "Common-mode choke",
    (
        ParamSpec("distance", "Distance from feed", "length", 0.0, minimum=0.0,
                  help="Position along the coax, measured from the feed point."),
        ParamSpec("choke_type", "Type", "choice", "perfect",
                  choices=(("perfect", "Perfect (blocks all common mode)"),
                           ("impedance", "Known impedance (e.g. ferrite)"),
                           ("air_coil", "Coax wound on a form (air core)"))),
        ParamSpec("r_ohm", "Resistance", "resistance", 1000.0, minimum=0.0,
                  help="Resistive part of the choke impedance at the design frequency. "
                       "Ferrite chokes at HF are mostly resistive.",
                  visible_when=("choke_type", ("impedance",))),
        ParamSpec("x_ohm", "Reactance", "resistance", 0.0, minimum=-100000.0,
                  help="Reactive part: positive is inductive, negative capacitive. Held "
                       "constant across the sweep.",
                  visible_when=("choke_type", ("impedance",))),
        ParamSpec("turns", "Turns", "int", 8, minimum=1, maximum=100,
                  visible_when=("choke_type", ("air_coil",))),
        ParamSpec("form_diameter", "Form diameter", "small_length", 0.06, minimum=0.005,
                  help="Outside diameter of the pipe or form the coax is wound on. "
                       "Turns are assumed close wound.",
                  visible_when=("choke_type", ("air_coil",))),
        ParamSpec("q", "Coil Q", "float", 50.0, minimum=1.0, maximum=1000.0,
                  help="Sets the loss, and so the peak impedance at self-resonance.",
                  visible_when=("choke_type", ("air_coil",))),
    ),
    max_count=4,
)

PART_TYPES: dict[str, PartType] = {p.kind: p for p in (RADIALS, TOP_HAT, LOADING_COIL,
                                                        COAX_RUN, CHOKE)}

# Parts that belong to the feed system rather than the antenna. They work with
# every template and are only active while the coax shield is modelled.
FEEDLINE_PART_KINDS = ("coax_run", "choke")


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
              visible_when=("coax", tuple(COAX)),
              hidden_when=("common_mode", (True,))),
    ParamSpec("common_mode", "Model coax shield (common mode)", "bool", False,
              help="Adds the outside of the coax shield to the model as a wire, following "
                   "the coax runs under Feed system, so current on the shield, its "
                   "radiation and the effect of chokes are simulated."),
    ParamSpec("radio_end", "Radio end", "choice", "floating",
              choices=(("floating", "Floating (radio not earthed)"),
                       ("earthed", "Earthed (wire to ground)")),
              help="Floating: battery-powered or portable radio. Earthed: the radio "
                   "chassis is wired straight down to ground.",
              visible_when=("common_mode", (True,))),
    ParamSpec("radio_height", "Radio height", "length", 1.0, minimum=0.05,
              help="The coax ends at the radio, straight below or above the end of the "
                   "last coax run.",
              visible_when=("common_mode", (True,))),
    ParamSpec("earth_resistance", "Earth connection resistance", "resistance", 0.0,
              minimum=0.0, help="Resistance of the ground rod or earth lead connection.",
              visible_when=("radio_end", ("earthed",))),
    ParamSpec("extra_length", "Extra coax at the radio", "length", 0.0, minimum=0.0,
              help="Coax beyond the modelled route, e.g. coiled up at the radio. Counts for "
                   "feedline loss and impedance transformation only.",
              visible_when=("common_mode", (True,))),
    ParamSpec("cm_target", "Common-mode target", "percent", 10.0, minimum=0.1, maximum=100.0,
              help="Largest acceptable current on the coax shield, in % of the antenna "
                   "current. 10 % (−20 dB) is a common rule of thumb.",
              visible_when=("common_mode", (True,))),
)

SIMULATION_SPECS = (
    ParamSpec("design_mhz", "Design frequency", "frequency", 14.2, minimum=0.1, maximum=3000.0),
    ParamSpec("sweep_start", "Sweep start", "frequency", 13.5, minimum=0.1, maximum=3000.0),
    ParamSpec("sweep_stop", "Sweep stop", "frequency", 15.0, minimum=0.1, maximum=3000.0),
    ParamSpec("sweep_points", "Sweep points", "int", 31, minimum=2, maximum=401),
    ParamSpec("segments_per_wavelength", "Segments per wavelength", "int", 20,
              minimum=10, maximum=100,
              help="Higher is more accurate and slower. 20 is a good default. Physically "
                   "small antennas also get at least 40 segments across their size, "
                   "whatever this is set to."),
    ParamSpec("swr_threshold", "SWR bandwidth threshold", "float", 2.0,
              minimum=1.1, maximum=10.0),
)
