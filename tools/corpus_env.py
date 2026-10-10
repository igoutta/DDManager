"""The corpus environment: ``<repo>/.corpus`` defaults plus the detected mods root.

    python tools/corpus_env.py               prints DDM_SAVE_CORPUS, DDM_STATE_CORPUS, DDM_MODS_ROOT
    python tools/corpus_env.py -- <command>  runs the command with the variables set

A variable that is already set in the environment wins; one whose default does not exist on
this machine is left unset, so the corpus tests skip with their own reason.  The mods root comes
from ``.corpus/manifest.json`` (written by ``tools/make_corpus.py``) or, failing that, from the
app's own detection.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from src.services.detection import InstallDetector, ManualPaths
from src.services.environment import Environment

ROOT = Path(__file__).absolute().parent.parent
CORPUS = ROOT / ".corpus"
NAMES = ("DDM_SAVE_CORPUS", "DDM_STATE_CORPUS", "DDM_MODS_ROOT")


def _manifest_mods_root() -> Path | None:
    manifest = CORPUS / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        value = json.loads(manifest.read_text("utf-8")).get("mods_root")
    except OSError, ValueError:
        return None
    return Path(value) if isinstance(value, str) and value else None


def _detected_mods_root() -> Path | None:
    snapshot = InstallDetector(Environment.from_host()).detect(ManualPaths(), None)
    if snapshot.primary_mods_dir is not None:
        return snapshot.primary_mods_dir
    return snapshot.workshop_dirs[0] if snapshot.workshop_dirs else None


def defaults() -> dict[str, str]:
    """The three variables with their defaults; a default that does not exist is left out."""
    saves = CORPUS / "saves"
    state = CORPUS / "state" / "mod_state.json"
    mods_root = _manifest_mods_root() or _detected_mods_root()
    found: dict[str, str] = {}
    if saves.is_dir() and any(saves.glob("*.json")):
        found["DDM_SAVE_CORPUS"] = str(saves)
    if state.is_file():
        found["DDM_STATE_CORPUS"] = str(state)
    if mods_root is not None and mods_root.is_dir():
        found["DDM_MODS_ROOT"] = str(mods_root)
    return found


def resolved() -> dict[str, str]:
    """``defaults()`` overridden by whatever the environment already sets."""
    values = defaults()
    for name in NAMES:
        if os.environ.get(name):
            values[name] = os.environ[name]
    return values


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    values = resolved()
    if args and args[0] == "--":
        if len(args) == 1:
            print("usage: corpus_env.py -- <command> [args...]")
            return 2
        env = {**os.environ, **values}
        return subprocess.run(args[1:], env=env, check=False).returncode
    for name in NAMES:
        print(f"{name}={values.get(name, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
