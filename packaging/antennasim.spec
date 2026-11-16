# PyInstaller spec for the Windows release: one folder, no console window.
#
# One-folder rather than one-file: it starts faster (nothing to unpack on each
# launch), and it keeps the Qt libraries as separate replaceable files, which
# the LGPL asks for. nec2c.exe goes to _internal/bin, where find_nec2c() looks
# when the app is frozen.

from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[(str(ROOT / "bin" / "nec2c.exe"), "bin")],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AntennaSim",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="AntennaSim")
