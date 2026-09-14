"""Solver-independent result containers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class PowerBudget:
    input_w: float
    radiated_w: float
    structure_loss_w: float
    network_loss_w: float

    @property
    def efficiency(self) -> float:
        return self.radiated_w / self.input_w if self.input_w > 0 else 0.0


@dataclass
class Pattern:
    """Far-field gain on a regular grid.

    theta is measured from zenith (NEC convention); elevation = 90 - theta.
    Gains are dBi arrays of shape (len(theta), len(phi)).
    """

    theta_deg: np.ndarray
    phi_deg: np.ndarray
    gain_vert_dbi: np.ndarray
    gain_hor_dbi: np.ndarray
    gain_total_dbi: np.ndarray


@dataclass
class FrequencyResult:
    freq_mhz: float
    z_in: complex
    power: PowerBudget | None = None
    # Segment currents in NEC order (wire by wire), amps for a 1 V source.
    currents: np.ndarray | None = None
    pattern: Pattern | None = None


@dataclass
class SolveResult:
    sweep: list[FrequencyResult]
    design: FrequencyResult | None
    raw_output: str = ""

    def frequencies(self) -> np.ndarray:
        return np.array([r.freq_mhz for r in self.sweep])

    def impedances(self) -> np.ndarray:
        return np.array([r.z_in for r in self.sweep])


class SolverError(RuntimeError):
    pass
