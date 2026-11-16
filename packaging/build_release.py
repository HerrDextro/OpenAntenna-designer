"""Build the Windows release: a folder with AntennaSim.exe, zipped.

Usage:  python packaging/build_release.py

Needs bin/nec2c.exe (python third_party/build_nec2c.py) and PyInstaller
(pip install -e ".[release]"). Writes dist/AntennaSim-<version>-windows-x64.zip.
In GitHub Actions it also reports the zip path and version as step outputs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
APP = DIST / "AntennaSim"


def project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def release_version(version: str, tag: str | None, commit: str | None) -> str:
    """Version used in the zip name.

    version: from pyproject.toml, e.g. "0.2.0"
    tag:     the git tag being released, e.g. "v0.2.0", or None for an ordinary build
    commit:  short commit hash in CI, else None
    """
    if tag is None:
        # Builds between releases must never look like a release.
        return f"{version}-dev-{commit}" if commit else f"{version}-dev"
    # Release tags are "v" + the pyproject version, optionally with a pre-release
    # suffix for trying out the pipeline: v0.2.0, or v0.2.0-rc1.
    if not tag.startswith("v"):
        raise SystemExit(f"Release tags start with 'v' (e.g. v{version}); got {tag!r}.")
    base, dash, suffix = tag[1:].partition("-")
    if base != version or (dash and not suffix):
        raise SystemExit(f"Tag {tag!r} does not match version {version!r} in pyproject.toml. "
                         f"Use v{version} or v{version}-rc1, or update pyproject.toml.")
    return tag[1:]


def main() -> int:
    tag = os.environ.get("GITHUB_REF_NAME") if os.environ.get("GITHUB_REF_TYPE") == "tag" else None
    commit = os.environ.get("GITHUB_SHA", "")[:7] or None
    version = release_version(project_version(), tag, commit)

    if not (ROOT / "bin" / "nec2c.exe").is_file():
        print("error: bin/nec2c.exe missing; run python third_party/build_nec2c.py",
              file=sys.stderr)
        return 1

    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(DIST), "--workpath", str(ROOT / "build"),
                    str(ROOT / "packaging" / "antennasim.spec")], check=True)

    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, APP / name)
    # GPL v3: the solver's complete source travels with its binary.
    shutil.copytree(ROOT / "third_party", APP / "third_party", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))

    archive = shutil.make_archive(str(DIST / f"AntennaSim-{version}-windows-x64"), "zip",
                                  DIST, APP.name)
    print(f"built {archive}")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"archive={archive}\nversion={version}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
