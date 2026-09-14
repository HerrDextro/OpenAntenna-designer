"""Build the vendored nec2c solver into bin/nec2c(.exe).

nec2c is GPL-2 licensed and is run by AntennaSim as a separate process, so the
application itself is not bound by its license.

Usage:  python third_party/build_nec2c.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "nec2c"
COMPAT = ROOT / "nec2c_compat"
OUT_DIR = ROOT.parent / "bin"

SOURCES = [
    "calculations.c", "geometry.c", "input.c", "matrix.c", "network.c",
    "shared.c", "fields.c", "ground.c", "main.c", "misc.c", "radiation.c",
    "somnec.c",
]


def main() -> int:
    cc = shutil.which("gcc") or shutil.which("cc")
    if cc is None:
        print("error: no C compiler (gcc) found on PATH", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(exist_ok=True)
    exe = OUT_DIR / ("nec2c.exe" if sys.platform == "win32" else "nec2c")
    # PACKAGE_STRING normally comes from autoconf's config.h.
    cmd = [cc, "-O2", "-std=gnu99", "-w", '-DPACKAGE_STRING="nec2c (AntennaSim build)"',
           "-o", str(exe)]
    if sys.platform == "win32":
        cmd += [f"-I{COMPAT}", "-static"]
    cmd += [str(SRC / s) for s in SOURCES] + ["-lm"]

    print(" ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f"built {exe}")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
