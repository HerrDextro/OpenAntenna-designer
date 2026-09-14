"""Ground-loss resistance estimate for ground-mounted verticals.

NEC2 cannot model radials buried in or lying on lossy ground, so their effect
is represented by a series loss resistance at the feed point. This is a rough
rule-of-thumb fit to commonly published measurements for a quarter-wave
vertical (e.g. ~30 Ω with 4 quarter-wave radials, ~8 Ω with 32, a few ohms with
120) and should be treated as an estimate. Users can override it manually.
"""

from __future__ import annotations

from ..model.units import wavelength_m

# How lossy the soil is relative to "average" ground.
_SOIL_FACTOR = {
    "very_poor": 1.6,
    "poor": 1.3,
    "average": 1.0,
    "good": 0.6,
    "fresh_water": 1.2,
    "salt_water": 0.05,
}

_R_MIN = 2.0  # dense radial field
_A = 45.4
_K = 1.61


def estimate_ground_loss(radial_count: int, radial_length_m: float, freq_mhz: float,
                         soil: str) -> float:
    length_wl = min(radial_length_m / wavelength_m(freq_mhz), 0.5)
    # Fit: R = R_min + A / (1 + N*L/K) with L in wavelengths, giving ~30 Ω for
    # 4 × λ/4, ~10 Ω for 32 × λ/4 and ~4 Ω for 120 × λ/4. No radials ≈ 47 Ω.
    coverage = max(radial_count, 0) * length_wl
    r = _R_MIN + _A / (1 + coverage / _K)
    return r * _SOIL_FACTOR.get(soil, 1.0)
