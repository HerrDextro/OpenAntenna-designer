"""NEC2 backend: runs the nec2c executable on a generated deck and parses its
text output. Running it as a separate process keeps nec2c's GPL licence
separate from the application."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from .base import SolveRequest, SolverBackend
from .nec_deck import solver_deck
from .results import FrequencyResult, PowerBudget, SolveResult, SolverError

_EXE = "nec2c.exe" if sys.platform == "win32" else "nec2c"


def find_nec2c() -> Path | None:
    candidates = []
    if env := os.environ.get("ANTENNASIM_NEC2C"):
        candidates.append(Path(env))
    if getattr(sys, "frozen", False):
        candidates.append(Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "bin" / _EXE)
    candidates.append(Path(__file__).resolve().parents[3] / "bin" / _EXE)
    for c in candidates:
        if c.is_file():
            return c
    found = shutil.which("nec2c")
    return Path(found) if found else None


_FREQ_RE = re.compile(r"FREQUENCY\s*[:=]\s*([-+0-9.Ee]+)\s*MHZ", re.IGNORECASE)
_POWER_RE = {
    "input": re.compile(r"INPUT POWER\s*=\s*([-+0-9.Ee]+)"),
    "radiated": re.compile(r"RADIATED POWER\s*=\s*([-+0-9.Ee]+)"),
    "structure": re.compile(r"STRUCTURE LOSS\s*=\s*([-+0-9.Ee]+)"),
    "network": re.compile(r"NETWORK LOSS\s*=\s*([-+0-9.Ee]+)"),
}


def _rows(lines: list[str], start: int):
    """Yield whitespace-split numeric rows after a table header until a blank line."""
    i = start
    # skip header lines until the first row that starts with an integer
    while i < len(lines) and not re.match(r"^\s*\d+\s", lines[i]):
        i += 1
    while i < len(lines) and lines[i].strip():
        yield lines[i].split()
        i += 1


def parse_output(text: str) -> list[FrequencyResult]:
    lines = text.splitlines()
    results: list[FrequencyResult] = []
    current: FrequencyResult | None = None
    power: dict[str, float] = {}

    for i, line in enumerate(lines):
        m = _FREQ_RE.search(line)
        if m and "WAVELENGTH" not in line:
            current = FrequencyResult(float(m.group(1)), complex(np.nan, np.nan))
            results.append(current)
            power = {}
            continue
        if current is None:
            continue
        if "ANTENNA INPUT PARAMETERS" in line:
            for row in _rows(lines, i + 1):
                current.z_in = complex(float(row[6]), float(row[7]))
                break
        elif "CURRENTS AND LOCATION" in line:
            vals = [complex(float(r[6]), float(r[7])) for r in _rows(lines, i + 1)]
            current.currents = np.array(vals, dtype=complex)
        else:
            for key, rx in _POWER_RE.items():
                pm = rx.search(line)
                if pm:
                    power[key] = float(pm.group(1))
                    if key == "network":
                        current.power = PowerBudget(power.get("input", 0.0),
                                                    power.get("radiated", 0.0),
                                                    power.get("structure", 0.0),
                                                    power["network"])
    return results


class Nec2Backend(SolverBackend):
    name = "NEC2 (nec2c)"

    def __init__(self, executable: Path | None = None, timeout_s: float = 300.0):
        self.executable = executable or find_nec2c()
        self.timeout_s = timeout_s

    def solve(self, request: SolveRequest) -> SolveResult:
        if self.executable is None:
            raise SolverError("nec2c executable not found. Build it with "
                              "'python third_party/build_nec2c.py' or set ANTENNASIM_NEC2C.")
        deck = solver_deck(request.model, list(request.sweep_mhz), request.design_mhz)
        with tempfile.TemporaryDirectory(prefix="antsim") as tmp:
            # nec2c limits file names to 75 characters, so use short relative names.
            Path(tmp, "in.nec").write_text(deck)
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            try:
                proc = subprocess.run([str(self.executable), "-iin.nec", "-oout.txt"],
                                      cwd=tmp, capture_output=True, text=True,
                                      timeout=self.timeout_s, creationflags=flags)
            except subprocess.TimeoutExpired as e:
                raise SolverError("NEC2 timed out") from e
            out_path = Path(tmp, "out.txt")
            output = out_path.read_text(errors="replace") if out_path.exists() else ""
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout).strip() or f"exit code {proc.returncode}"
            raise SolverError(f"NEC2 failed: {msg}")

        blocks = parse_output(output)
        expected = len(request.sweep_mhz) + 1
        if len(blocks) != expected or any(np.isnan(b.z_in.real) for b in blocks):
            raise SolverError(f"NEC2 output incomplete ({len(blocks)} of {expected} "
                              "frequencies solved)")
        return SolveResult(sweep=blocks[:-1], design=blocks[-1], raw_output=output)
