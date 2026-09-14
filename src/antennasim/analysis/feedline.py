"""Feed system: ideal impedance transformer followed by a lossy transmission line."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..model.materials import COAX
from ..model.units import C0


@dataclass
class FeedResult:
    z_rig: np.ndarray  # impedance seen at the radio end
    matched_loss_db: np.ndarray
    total_loss_db: np.ndarray  # matched + mismatch-induced additional loss


def transform_through_line(z_load: np.ndarray, z0: float, alpha_np_per_m: np.ndarray,
                           beta_rad_per_m: np.ndarray, length_m: float) -> np.ndarray:
    gl = (alpha_np_per_m + 1j * beta_rad_per_m) * length_m
    t = np.tanh(gl)
    return z0 * (z_load + z0 * t) / (z0 + z_load * t)


def apply_feed_system(freqs_mhz: np.ndarray, z_antenna: np.ndarray, feedline: dict
                      ) -> FeedResult:
    freqs_mhz = np.asarray(freqs_mhz, dtype=float)
    z = np.asarray(z_antenna, dtype=complex) / feedline["transformer_ratio"]
    zeros = np.zeros_like(freqs_mhz)
    coax_key = feedline["coax"]
    if coax_key == "none" or feedline["length"] <= 0:
        return FeedResult(z, zeros, zeros)

    coax = COAX[coax_key]
    length = feedline["length"]
    ml_db = np.array([coax.matched_loss_db_per_m(f) * length for f in freqs_mhz])
    alpha = ml_db / length / (20 / math.log(10))  # dB/m -> Np/m
    beta = 2 * math.pi * freqs_mhz * 1e6 / (C0 * coax.velocity_factor)
    z_rig = transform_through_line(z, coax.z0, alpha, beta, length)

    rho = np.minimum(np.abs((z - coax.z0) / (z + coax.z0)), 0.999999)
    a = 10 ** (ml_db / 10)
    total = 10 * np.log10((a * a - rho * rho) / (a * (1 - rho * rho)))
    return FeedResult(z_rig, ml_db, total)
