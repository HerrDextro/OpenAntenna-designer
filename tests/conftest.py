import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest

from antennasim.solver.nec2_backend import Nec2Backend, find_nec2c


@pytest.fixture(scope="session")
def backend():
    if find_nec2c() is None:
        pytest.skip("nec2c not built (run python third_party/build_nec2c.py)")
    return Nec2Backend()


def run_nec_raw(deck: str) -> str:
    """Run a hand-written deck through nec2c and return the output text."""
    exe = find_nec2c()
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "in.nec").write_text(deck)
        subprocess.run([str(exe), "-iin.nec", "-oout.txt"], cwd=tmp, check=True,
                       capture_output=True)
        return Path(tmp, "out.txt").read_text()


def parse_rp_total_gain(text: str) -> dict[tuple[float, float], float]:
    """{(theta, phi): total gain dB} from NEC RADIATION PATTERNS tables."""
    gains = {}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "RADIATION PATTERNS" not in line:
            continue
        for row in lines[i + 5:]:
            if not row.strip():
                break
            parts = row.split()
            if not re.match(r"^-?\d", parts[0]):
                break
            gains[(float(parts[0]), float(parts[1]))] = float(parts[4])
    return gains
