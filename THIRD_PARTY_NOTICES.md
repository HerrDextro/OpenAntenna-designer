# Third-party components

AntennaSim's own code is under the MIT license with the Commons Clause (see
`LICENSE`). The Windows release also contains the following components, each
under its own license.

| Component | Used for | License |
|---|---|---|
| nec2c by Neoklis Kyriazis (5B4AZ) | NEC2 antenna solver, run as a separate program | GNU GPL v3 |
| [Qt](https://www.qt.io/) and [PySide6](https://doc.qt.io/qtforpython-6/) | user interface | GNU LGPL v3 |
| [pyqtgraph](https://www.pyqtgraph.org/) | plots | MIT |
| [NumPy](https://numpy.org/) | numerics | BSD 3-Clause |
| [Python](https://www.python.org/) | runtime, bundled by PyInstaller | PSF License |

## nec2c (GPL v3)

`nec2c.exe` is built unmodified from the source in `third_party/nec2c`, plus a
small compatibility header (`third_party/nec2c_compat`) so it compiles with
MinGW on Windows. The complete source and build script are included in the
release under `third_party/`, and the license text is in
`third_party/nec2c/COPYING`. AntennaSim talks to nec2c only through files and
a separate process, so the GPL applies to nec2c alone.

## Qt / PySide6 (LGPL v3)

The release ships the Qt and PySide6 libraries as separate, unmodified DLL and
`.pyd` files in the `_internal` folder, so they can be replaced with other
compatible versions. Their source code is available from the Qt Project at
https://download.qt.io/official_releases/ and
https://code.qt.io/cgit/pyside/pyside-setup.git/.
