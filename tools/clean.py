"""Remove build artifacts and caches. Never touches 'DD Manager Data', release/ or .venv."""

import shutil
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent
TARGETS = ("build", "dist", ".pytest_cache", ".ruff_cache")


def main() -> int:
    for name in TARGETS:
        target = ROOT / name
        if target.is_dir():
            shutil.rmtree(target)
            print(f"removed {target}")
    for cache in ROOT.rglob("__pycache__"):
        if ".venv" in cache.parts:
            continue
        shutil.rmtree(cache, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
