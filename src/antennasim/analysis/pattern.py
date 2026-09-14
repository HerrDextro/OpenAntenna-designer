"""Pattern metrics and cuts."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..solver.results import Pattern


@dataclass
class PatternSummary:
    max_gain_dbi: float
    max_elevation_deg: float  # take-off angle
    max_azimuth_deg: float
    elevation_beamwidth_deg: float | None


def summarize(p: Pattern) -> PatternSummary:
    g = p.gain_total_dbi
    it, ip = np.unravel_index(int(np.argmax(g)), g.shape)
    elev = 90.0 - float(p.theta_deg[it])

    # Parabolic refinement of the take-off angle along theta.
    if 0 < it < len(p.theta_deg) - 1:
        y0, y1, y2 = g[it - 1, ip], g[it, ip], g[it + 1, ip]
        denom = y0 - 2 * y1 + y2
        if denom < 0:
            step = p.theta_deg[1] - p.theta_deg[0]
            elev = 90.0 - float(p.theta_deg[it] + 0.5 * (y0 - y2) / denom * step)

    return PatternSummary(float(g[it, ip]), elev, float(p.phi_deg[ip]),
                          _beamwidth(p.theta_deg, g[:, ip], it))


def _beamwidth(theta: np.ndarray, cut: np.ndarray, i_max: int) -> float | None:
    level = cut[i_max] - 3.0

    def cross(direction: int) -> float | None:
        i = i_max
        while 0 <= i + direction < len(cut):
            j = i + direction
            if cut[j] < level:
                t = (cut[i] - level) / (cut[i] - cut[j])
                return float(theta[i] + t * (theta[j] - theta[i]))
            i = j
        return None

    lo, hi = cross(-1), cross(1)
    if lo is None or hi is None:
        return None
    return abs(hi - lo)


def elevation_cut(p: Pattern, azimuth_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """(elevation angles, gain) in the vertical plane through azimuth, covering
    both the azimuth and the opposite direction (elevation 0..180)."""
    ip = _nearest_phi(p, azimuth_deg)
    io = _nearest_phi(p, azimuth_deg + 180.0)
    elev_front = 90.0 - p.theta_deg  # free-space patterns include negative elevations
    angles = np.concatenate([elev_front[::-1], 180.0 - elev_front[1:]])
    gains = np.concatenate([p.gain_total_dbi[::-1, ip], p.gain_total_dbi[1:, io]])
    return angles, gains


def _nearest_phi(p: Pattern, azimuth_deg: float) -> int:
    diff = (p.phi_deg - azimuth_deg + 180.0) % 360.0 - 180.0
    return int(np.argmin(np.abs(diff)))


def azimuth_cut(p: Pattern, elevation_deg: float) -> tuple[np.ndarray, np.ndarray]:
    it = int(np.argmin(np.abs((90.0 - p.theta_deg) - elevation_deg)))
    return p.phi_deg, p.gain_total_dbi[it, :]
