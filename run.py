"""Run DD Manager from a source checkout, pinned to ``<repo>/DD Manager Data``."""

import sys
from pathlib import Path

from src.app import main

ROOT = Path(__file__).absolute().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


raise SystemExit(main(["--data-dir", str(ROOT / "DD Manager Data"), *sys.argv[1:]]))
