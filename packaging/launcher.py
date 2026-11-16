"""Entry point for the frozen (PyInstaller) build.

PyInstaller runs its entry script as a top-level module, where the package's
own __main__.py and its relative import would fail.
"""

import sys

from antennasim.app import main

sys.exit(main())
