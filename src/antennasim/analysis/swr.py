"""SWR, resonance and bandwidth."""

from __future__ import annotations

import numpy as np


def reflection(z: np.ndarray | complex, z0: float) -> np.ndarray:
    z = np.asarray(z, dtype=complex)
    return (z - z0) / (z + z0)


def swr(z: np.ndarray | complex, z0: float) -> np.ndarray:
    rho = np.minimum(np.abs(reflection(z, z0)), 0.999999)
    return (1 + rho) / (1 - rho)


def return_loss_db(z: np.ndarray | complex, z0: float) -> np.ndarray:
    rho = np.maximum(np.abs(reflection(z, z0)), 1e-12)
    return -20 * np.log10(rho)


def resonances(freqs: np.ndarray, z: np.ndarray) -> list[float]:
    """Frequencies where reactance crosses zero (linear interpolation)."""
    x = np.imag(z)
    out = []
    for i in range(len(freqs) - 1):
        if x[i] == 0:
            out.append(float(freqs[i]))
        elif x[i] * x[i + 1] < 0:
            t = x[i] / (x[i] - x[i + 1])
            out.append(float(freqs[i] + t * (freqs[i + 1] - freqs[i])))
    if len(x) and x[-1] == 0:
        out.append(float(freqs[-1]))
    return out


def bandwidth(freqs: np.ndarray, swr_values: np.ndarray, threshold: float
              ) -> tuple[float, float] | None:
    """Edges of the contiguous band around the SWR minimum where SWR <= threshold.

    Edges touching the ends of the sweep are returned as the sweep limit.
    """
    if len(freqs) == 0:
        return None
    i_min = int(np.argmin(swr_values))
    if swr_values[i_min] > threshold:
        return None

    def edge(i_in: int, i_out: int) -> float:
        s_in, s_out = swr_values[i_in], swr_values[i_out]
        t = (threshold - s_in) / (s_out - s_in) if s_out != s_in else 0.0
        return float(freqs[i_in] + t * (freqs[i_out] - freqs[i_in]))

    lo = i_min
    while lo > 0 and swr_values[lo - 1] <= threshold:
        lo -= 1
    hi = i_min
    while hi < len(freqs) - 1 and swr_values[hi + 1] <= threshold:
        hi += 1
    f_lo = edge(lo, lo - 1) if lo > 0 else float(freqs[0])
    f_hi = edge(hi, hi + 1) if hi < len(freqs) - 1 else float(freqs[-1])
    return f_lo, f_hi
