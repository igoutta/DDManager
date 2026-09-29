"""PyInstaller entry point for the frozen ``DD Manager.exe``.

With no arguments the CLI launches the GUI; ``--self-test`` (used by the build script and CI)
checks the frozen bundle and exits.
"""

from src.cli import main

raise SystemExit(main())
