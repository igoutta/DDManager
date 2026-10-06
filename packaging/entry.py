"""PyInstaller entry point for the frozen ``DD Manager.exe``.

With no arguments the CLI launches the GUI; ``--self-test`` (used by the build script and CI)
checks the frozen bundle and exits.

The exe is a windowed (no-console) app, so Windows starts it without stdout/stderr when it is
launched from a terminal without redirection. Reuse the parent's console for command-line use
(``--self-test``, ``--version``, ``scan``) and fall back to a null sink for a double-click.
"""

import ctypes
import os
import sys
from pathlib import Path

ATTACH_PARENT_PROCESS = -1


def _attach_console() -> None:
    if sys.stdout is not None and sys.stderr is not None:
        return  # redirected to a file/pipe: the handles are already usable
    attached = bool(ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS))
    target = Path("CONOUT$" if attached else os.devnull)  # CONOUT$ is the console device
    stream = target.open("w", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream


if sys.platform == "win32":
    _attach_console()

from src.cli import main  # noqa: E402  (the console must be attached before anything prints)

raise SystemExit(main())
