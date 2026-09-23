"""Tune one parameter so the antenna is resonant (X = 0) at a target frequency."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable


@dataclass
class TuneResult:
    value: float
    reactance: float
    iterations: int
    converged: bool
    message: str = ""


def find_resonance(func: Callable[[float], float], lo: float, hi: float, tol_x: float,
                   tol_f: float = 0.5, scan_points: int = 24, max_iter: int = 30) -> TuneResult:
    """Find the lowest-order resonance of X(value) between lo and hi.

    Lengthening an element or adding inductance or capacitive loading moves
    reactance upward through the fundamental (quarter- or half-wave) resonance.
    Further up, X jumps from large positive to large negative at an
    antiresonance (a pole, not a zero) and then crosses zero again at a
    higher-order resonance. We therefore scan upward from `lo` and take the
    first negative-to-positive crossing, skipping poles, then refine it.
    """
    iterations = 0

    def f(x: float) -> float:
        nonlocal iterations
        iterations += 1
        return func(x)

    step = (hi - lo) / scan_points
    xs = [lo + step * i for i in range(scan_points + 1)]
    prev_x, prev_f = xs[0], f(xs[0])
    if abs(prev_f) <= tol_f:
        return TuneResult(prev_x, prev_f, iterations, True)
    start_f = prev_f
    bracket = None
    for x in xs[1:]:
        fx = f(x)
        if math.isnan(fx):  # the model rejected this value; don't bracket across it
            prev_x, prev_f = x, fx
            continue
        if abs(fx) <= tol_f:
            return TuneResult(x, fx, iterations, True)
        if prev_f < 0 < fx:
            bracket = (prev_x, prev_f, x, fx)
            break
        prev_x, prev_f = x, fx

    if bracket is None:
        # Starting negative without ever crossing upward means X stayed negative.
        if start_f > 0:
            msg = ("Already electrically too long at the smallest value, so this parameter "
                   "can't reach resonance. Shorten another part (for example the element) "
                   "instead.")
        else:
            msg = ("Still electrically too short at the largest value tried. Lengthen "
                   "another part or add loading.")
        return TuneResult(xs[0], start_f, iterations, False, msg)

    # Illinois false position inside the bracket; X is monotonic there.
    a, fa, b, fb = bracket
    side = 0
    x, fx = a, fa
    for _ in range(max_iter):
        x = (a * fb - b * fa) / (fb - fa)
        fx = f(x)
        if abs(fx) <= tol_f or abs(b - a) <= tol_x:
            break
        if fx > 0:
            b, fb = x, fx
            if side == -1:
                fa /= 2
            side = -1
        else:
            a, fa = x, fx
            if side == 1:
                fb /= 2
            side = 1
    converged = abs(fx) <= tol_f * 4
    return TuneResult(x, fx, iterations, converged,
                      "" if converged else "Did not fully converge; check the result.")
