"""Tune one parameter so the antenna is resonant (X = 0) at a target frequency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class TuneResult:
    value: float
    reactance: float
    iterations: int
    converged: bool
    message: str = ""


def find_root(func: Callable[[float], float], lo: float, hi: float, tol_x: float,
              tol_f: float = 0.5, max_iter: int = 30, scan_points: int = 6) -> TuneResult:
    """Bracketing root finder (Illinois false position) for a noisy-ish objective.

    If lo/hi do not bracket a sign change, the range is scanned first.
    """
    iterations = 0

    def f(x):
        nonlocal iterations
        iterations += 1
        return func(x)

    f_lo, f_hi = f(lo), f(hi)
    if f_lo * f_hi > 0:
        xs = [lo + (hi - lo) * i / (scan_points + 1) for i in range(1, scan_points + 1)]
        prev_x, prev_f = lo, f_lo
        found = False
        for x in xs + [hi]:
            fx = f_hi if x == hi else f(x)
            if prev_f * fx <= 0:
                lo, f_lo, hi, f_hi = prev_x, prev_f, x, fx
                found = True
                break
            prev_x, prev_f = x, fx
        if not found:
            best = min([(abs(f_lo), lo, f_lo), (abs(f_hi), hi, f_hi)])
            return TuneResult(best[1], best[2], iterations, False,
                              "No resonance found in the search range.")

    side = 0
    x = lo
    fx = f_lo
    for _ in range(max_iter):
        if f_hi == f_lo:
            break
        x = (lo * f_hi - hi * f_lo) / (f_hi - f_lo)
        fx = f(x)
        if abs(fx) <= tol_f or abs(hi - lo) <= tol_x:
            return TuneResult(x, fx, iterations, True)
        if fx * f_hi > 0:
            hi, f_hi = x, fx
            if side == -1:
                f_lo /= 2
            side = -1
        else:
            lo, f_lo = x, fx
            if side == 1:
                f_hi /= 2
            side = 1
    return TuneResult(x, fx, iterations, abs(fx) <= tol_f * 4,
                      "" if abs(fx) <= tol_f * 4 else "Did not fully converge.")
