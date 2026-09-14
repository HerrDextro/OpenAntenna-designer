"""Solver backend interface, so NEC2 can be swapped for another engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..geometry.wire_model import WireModel
from .results import SolveResult


@dataclass(frozen=True)
class SolveRequest:
    """The backend solves currents and input impedance.

    `model.ground` is the ground used for the current solution; the far-field
    pattern is computed separately from the design-frequency currents.
    """

    model: WireModel  # already segmented
    sweep_mhz: tuple[float, ...]
    design_mhz: float  # currents are returned for this frequency


class SolverBackend(ABC):
    name: str

    @abstractmethod
    def solve(self, request: SolveRequest) -> SolveResult:
        ...
