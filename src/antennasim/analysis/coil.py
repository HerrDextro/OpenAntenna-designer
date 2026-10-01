"""Single-layer air-core coil design (Wheeler's formula)."""

from __future__ import annotations

import math
from dataclasses import dataclass

_IN = 0.0254


@dataclass
class CoilDesign:
    turns: float
    coil_length_m: float
    wire_length_m: float
    form_diameter_m: float
    pitch_m: float
    inductance_uh: float  # check value from Wheeler with the solved turns


def wheeler_inductance_uh(turns: float, diameter_m: float, length_m: float) -> float:
    """L = d² n² / (18 d + 40 l), d and l in inches (accurate to ~1% for l > 0.4 d)."""
    d, l = diameter_m / _IN, length_m / _IN
    return d * d * turns * turns / (18 * d + 40 * l)


def design_coil(inductance_uh: float, form_diameter_m: float, wire_diameter_m: float,
                spacing_ratio: float = 1.0) -> CoilDesign:
    """Turns needed for a target inductance.

    `form_diameter_m` is the mean coil diameter; `spacing_ratio` is pitch divided
    by wire diameter (1.0 = close wound).
    """
    if inductance_uh <= 0:
        return CoilDesign(0.0, 0.0, 0.0, form_diameter_m, 0.0, 0.0)
    d = form_diameter_m / _IN
    p = wire_diameter_m * spacing_ratio / _IN
    L = inductance_uh
    # d² n² - 40 L p n - 18 L d = 0
    n = (40 * L * p + math.sqrt((40 * L * p) ** 2 + 72 * L * d ** 3)) / (2 * d * d)
    length = n * p * _IN
    return CoilDesign(
        turns=n,
        coil_length_m=length,
        wire_length_m=n * math.pi * form_diameter_m,
        form_diameter_m=form_diameter_m,
        pitch_m=p * _IN,
        inductance_uh=wheeler_inductance_uh(n, form_diameter_m, length),
    )


def reactance_ohm(inductance_uh: float, freq_mhz: float) -> float:
    return 2 * math.pi * freq_mhz * inductance_uh


def medhurst_capacitance_pf(diameter_m: float, length_m: float) -> float:
    """Self-capacitance of a single-layer solenoid.

    Medhurst's measurements as fitted by D. W. Knight:
    C = D (0.1126 l/D + 0.08 + 0.27 / sqrt(l/D)) pF, with D and l in cm.
    """
    d, l = diameter_m * 100, length_m * 100
    ratio = max(l / d, 1e-3)
    return d * (0.1126 * ratio + 0.08 + 0.27 / math.sqrt(ratio))


@dataclass
class AirChoke:
    """Coax wound on a form: an inductor with self-capacitance, i.e. a parallel RLC."""

    turns: int
    mean_diameter_m: float
    coil_length_m: float
    coax_length_m: float  # coax used for the winding
    inductance_uh: float
    capacitance_pf: float
    resistance_ohm: float  # parallel loss resistance

    @property
    def self_resonance_mhz(self) -> float:
        return 1.0 / (2 * math.pi * math.sqrt(self.inductance_uh * 1e-6
                                              * self.capacitance_pf * 1e-12)) / 1e6

    def impedance(self, freq_mhz: float) -> complex:
        w = 2 * math.pi * freq_mhz * 1e6
        admittance = (1 / self.resistance_ohm + 1 / (1j * w * self.inductance_uh * 1e-6)
                      + 1j * w * self.capacitance_pf * 1e-12)
        return 1 / admittance


def air_choke(turns: int, form_diameter_m: float, coax_diameter_m: float, q: float,
              design_mhz: float) -> AirChoke:
    """Close-wound coax choke. Self-capacitance is estimated for a wire solenoid;
    coax windings usually have somewhat more, so the real choke resonates lower."""
    mean = form_diameter_m + coax_diameter_m
    length = turns * coax_diameter_m
    inductance = wheeler_inductance_uh(turns, mean, length)
    capacitance = medhurst_capacitance_pf(mean, length)
    resistance = q * 2 * math.pi * design_mhz * inductance
    return AirChoke(turns, mean, length, turns * math.pi * mean, inductance, capacitance,
                    resistance)
