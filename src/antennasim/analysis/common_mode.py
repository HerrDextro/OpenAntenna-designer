"""Common-mode current on the coax shield, and the choke needed to stop it.

The outside of the shield is a wire in the model and a choke is a series
impedance Zc in that wire. The structure is linear, so two 1 V solves give the
currents for every possible choke at once:

    A: drive the feed, choke point shorted
    B: drive the choke point, feed shorted

With the choke in place its voltage is V2 = -Zc * I2, so

    I2 = A[s2] / (1 + B[s2] * Zc)        (current through the choke)
    I  = A + B * V2                      (every segment current)

where s2 is the choke segment. A perfect choke (Zc -> inf) gives V2 = -A[s2] / B[s2].
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

MET = "met"  # below target without a choke
NEEDS = "needs"  # a choke of `resistance_ohm` or more reaches the target
UNREACHABLE = "unreachable"  # even a perfect choke here leaves too much

_GRID_OHM = np.logspace(0, 6, 361)  # 1 Ω to 1 MΩ


def currents_with_choke(a: np.ndarray, b: np.ndarray, s2: int, zc) -> np.ndarray:
    """Segment currents with a choke of impedance zc (scalar or array) at s2.

    Returns shape (N,) for a scalar zc, (len(zc), N) for an array.
    """
    zc_arr = np.atleast_1d(np.asarray(zc, dtype=complex))
    perfect = np.isinf(zc_arr.real)
    finite = np.where(perfect, 0, zc_arr)
    v2 = np.where(perfect, -a[s2] / b[s2], -finite * a[s2] / (1 + b[s2] * finite))
    out = a[None, :] + v2[:, None] * b[None, :]
    return out[0] if np.ndim(zc) == 0 else out


def shield_ratio(currents: np.ndarray, feed: int, shield: np.ndarray) -> np.ndarray:
    """Largest shield current relative to the feed current (works row-wise)."""
    cur = np.atleast_2d(currents)
    ratio = np.abs(cur[:, shield]).max(axis=1) / np.maximum(np.abs(cur[:, feed]), 1e-30)
    return ratio if np.ndim(currents) > 1 else ratio[0]


@dataclass
class ChokeRequirement:
    status: str
    resistance_ohm: float | None  # resistive choke impedance needed (NEEDS only)
    unchoked_ratio: float  # shield current / antenna current with no choke here
    perfect_ratio: float  # ... with a perfect choke here


def required_choke(a: np.ndarray, b: np.ndarray, feed: int, s2: int, shield: np.ndarray,
                   target: float) -> ChokeRequirement:
    """Smallest resistive choke at s2 that keeps the shield current below `target`
    (a fraction of the antenna current) on every segment in `shield`.

    Ferrite chokes are mostly resistive at HF, and a resistive choke cannot
    resonate with the shield, so the requirement is stated as a resistance.
    """
    unchoked = float(shield_ratio(a, feed, shield))
    perfect = float(shield_ratio(currents_with_choke(a, b, s2, math.inf), feed, shield))
    if unchoked <= target:
        return ChokeRequirement(MET, None, unchoked, perfect)
    if perfect > target:
        return ChokeRequirement(UNREACHABLE, None, unchoked, perfect)
    ratios = shield_ratio(currents_with_choke(a, b, s2, _GRID_OHM), feed, shield)
    bad = np.nonzero(ratios > target)[0]
    if len(bad) == 0:
        return ChokeRequirement(NEEDS, float(_GRID_OHM[0]), unchoked, perfect)
    i = bad[-1]
    if i + 1 >= len(_GRID_OHM):
        return ChokeRequirement(UNREACHABLE, None, unchoked, perfect)
    lo, hi = _GRID_OHM[i], _GRID_OHM[i + 1]
    for _ in range(30):  # bisect in log space between the last failing and first passing
        mid = math.sqrt(lo * hi)
        if shield_ratio(currents_with_choke(a, b, s2, mid), feed, shield) > target:
            lo = mid
        else:
            hi = mid
    return ChokeRequirement(NEEDS, hi, unchoked, perfect)


@dataclass
class CommonModeReport:
    """Shield currents from the actual simulation, plus the choke requirement."""

    at_feed: float  # shield current where it leaves the feed / antenna current
    peak: float
    peak_distance_m: float  # along the coax from the feed
    coax_length_m: float
    target: float
    requirement_distance_m: float  # where the requirement applies
    requirement: ChokeRequirement
    chokes: list[tuple[str, float, complex]] = field(default_factory=list)  # label, m, Z

    @staticmethod
    def db(ratio: float) -> float:
        return 20 * math.log10(max(ratio, 1e-12))
