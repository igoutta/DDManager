"""Load the legacy Tk app's modules from the pinned git commit, never from the working tree.

The rewrite proves parity against ``31e85d6`` (Release v0.2.1). Files are extracted with
``git show`` into a temporary directory and imported from there, so deleting the legacy
files from the working tree does not break the differential tests.
"""

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

LEGACY_COMMIT = "31e85d6"
LEGACY_FILES = (
    "dd2.py",
    "categories.py",
    "localization.py",
    "paths.py",
    "state.py",
    "legacy_loadout.py",
)
_MODULE_PREFIX = "legacy_oracle_"


def repo_root() -> Path:
    return Path(__file__).absolute().parent.parent


def extract(dest: Path | None = None) -> Path:
    """Write the pinned legacy files into ``dest`` (a fresh temp dir by default)."""
    dest = Path(tempfile.mkdtemp(prefix="ddm-legacy-")) if dest is None else dest
    dest.mkdir(parents=True, exist_ok=True)
    for name in LEGACY_FILES:
        blob = subprocess.run(
            ["git", "show", f"{LEGACY_COMMIT}:{name}"],
            cwd=repo_root(),
            check=True,
            capture_output=True,
        ).stdout
        (dest / name).write_bytes(blob)
    return dest


class LegacyOracle:
    """Imports the pinned legacy modules under private names so they never clash with ``src``."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._modules: dict[str, ModuleType] = {}

    def module(self, name: str) -> ModuleType:
        """Return the legacy module ``name`` (``dd2``, ``state``...), importing it on first use."""
        if name in self._modules:
            return self._modules[name]
        if name not in {Path(f).stem for f in LEGACY_FILES}:
            raise KeyError(name)
        # dd2 imports its helpers as top-level modules; make the oracle dir importable first.
        if str(self.directory) not in sys.path:
            sys.path.insert(0, str(self.directory))
        alias = _MODULE_PREFIX + name
        spec = importlib.util.spec_from_file_location(alias, self.directory / f"{name}.py")
        if spec is None or spec.loader is None:
            raise ImportError(name)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[alias] = mod
        spec.loader.exec_module(mod)
        self._modules[name] = mod
        return mod

    def stub_manager(self, identities: dict[str, tuple[str, str]]) -> object:
        """Stand-in for the Tk ``ModManager`` that the legacy save patcher calls back into."""

        class StubManager:
            def save_identity_for_mod(self, mod: str) -> tuple[str, str]:
                return identities[mod]

        return StubManager()


def main() -> int:
    dest = extract()
    print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
