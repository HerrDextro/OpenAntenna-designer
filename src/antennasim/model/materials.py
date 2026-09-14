"""Material, ground and coax reference data.

Coax loss figures are typical manufacturer values and are approximate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Conductivity in S/m.
CONDUCTORS: dict[str, tuple[str, float]] = {
    "copper": ("Copper", 5.8e7),
    "aluminum": ("Aluminium", 3.77e7),
    "brass": ("Brass", 1.59e7),
    "stainless": ("Stainless steel", 1.45e6),
    "copperweld": ("Copper-clad steel", 1.7e7),
    "perfect": ("Lossless (ideal)", math.inf),
}


@dataclass(frozen=True)
class GroundType:
    label: str
    conductivity: float  # S/m
    permittivity: float  # relative


GROUNDS: dict[str, GroundType] = {
    "very_poor": GroundType("Very poor (city / industrial)", 0.001, 3.0),
    "poor": GroundType("Poor (sandy, dry)", 0.002, 10.0),
    "average": GroundType("Average", 0.005, 13.0),
    "good": GroundType("Good (pastoral, rich soil)", 0.0303, 20.0),
    "fresh_water": GroundType("Fresh water", 0.001, 80.0),
    "salt_water": GroundType("Salt water", 5.0, 81.0),
}


@dataclass(frozen=True)
class CoaxType:
    label: str
    z0: float
    velocity_factor: float
    # Matched loss in dB per 100 ft at 10 MHz and 100 MHz; interpolated with
    # loss(f) = k1*sqrt(f) + k2*f (conductor + dielectric loss).
    loss_10: float
    loss_100: float

    def matched_loss_db_per_m(self, freq_mhz: float) -> float:
        # Solve k1*sqrt(10)+k2*10 = loss_10 and k1*10+k2*100 = loss_100.
        a11, a12, a21, a22 = math.sqrt(10.0), 10.0, 10.0, 100.0
        det = a11 * a22 - a12 * a21
        k1 = (self.loss_10 * a22 - a12 * self.loss_100) / det
        k2 = (a11 * self.loss_100 - self.loss_10 * a21) / det
        k1, k2 = max(k1, 0.0), max(k2, 0.0)
        per_100ft = k1 * math.sqrt(freq_mhz) + k2 * freq_mhz
        return per_100ft / 30.48


COAX: dict[str, CoaxType] = {
    "rg58": CoaxType("RG-58", 50.0, 0.66, 1.4, 4.9),
    "rg8x": CoaxType("RG-8X", 50.0, 0.78, 1.1, 3.7),
    "rg213": CoaxType("RG-213", 50.0, 0.66, 0.6, 2.2),
    "lmr400": CoaxType("LMR-400", 50.0, 0.85, 0.4, 1.3),
    "rg6": CoaxType("RG-6 (75 Ω)", 75.0, 0.82, 0.6, 2.0),
    "ladder450": CoaxType("450 Ω ladder line", 450.0, 0.91, 0.06, 0.3),
}


def awg_diameter_m(gauge: int) -> float:
    """Solid wire diameter for an AWG gauge."""
    return 0.127e-3 * 92 ** ((36 - gauge) / 39)
