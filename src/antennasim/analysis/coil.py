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
