"""Copy the user's real game saves and state file into ``<repo>/.corpus`` for the corpus check.

The app's own detection does the finding (``Environment.from_host``, ``InstallDetector``,
``resolve_app_paths``): every ``persist.game.json`` the game wrote, including the game's own
``backup/`` copy next to each one, is copied to
``.corpus/saves/<profile>[.backup].persist.game.json`` and the active ``mod_state.json`` to
``.corpus/state/mod_state.json``.  The originals are only read.  ``.corpus/manifest.json``
records where every copy came from and its SHA-256, and the three environment lines the corpus
tests use are printed at the end.

    python tools/make_corpus.py [--data-dir DIR] [--state FILE] [--dest DIR]

``--data-dir`` is the app's own override for the data folder (``DDMANAGER_DATA_DIR`` is honoured
too); ``--state`` names a ``mod_state.json`` explicitly when the active one lives elsewhere.
"""

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import src
from src.core.state_file import parse_state
from src.services.app_paths import resolve_app_paths
from src.services.detection import InstallDetector, InstallSnapshot, ManualPaths
from src.services.environment import Environment
from src.services.save_discovery import SAVE_FILE_NAME

ROOT = Path(__file__).absolute().parent.parent
DEFAULT_DEST = ROOT / ".corpus"
GAME_BACKUP_DIR = "backup"


@dataclass(frozen=True, slots=True)
class Copied:
    source: Path
    copy: Path
    size: int
    sha256: str

    def record(self) -> dict[str, Any]:
        return {
            "source": str(self.source),
            "copy": self.copy.name,
            "size": self.size,
            "sha256": self.sha256,
        }


def _optional_path(text: str) -> Path | None:
    return Path(text) if text.strip() else None


def _state_hints(state_path: Path) -> tuple[ManualPaths, Path | None]:
    """The manual paths and mods folder saved in the state, so detection sees what the app sees."""
    try:
        obj = json.loads(state_path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        print(f"note: {state_path} not readable ({exc}); detecting without it")
        return ManualPaths(), None
    doc, _ = parse_state(obj)
    settings = doc.settings
    manual = ManualPaths(
        game_root=_optional_path(settings.manual_game_root),
        local_mods=_optional_path(settings.manual_local_mods_path),
        workshop_mods=_optional_path(settings.manual_workshop_mods_path),
    )
    return manual, _optional_path(settings.mods_path)


def _copy_name(save: Path) -> str:
    """``profile_1.persist.game.json``; the game's ``backup/`` copy gets ``.backup`` inserted."""
    folder = save.parent
    if folder.name.casefold() == GAME_BACKUP_DIR:
        return f"{folder.parent.name}.{GAME_BACKUP_DIR}.{SAVE_FILE_NAME}"
    return f"{folder.name}.{SAVE_FILE_NAME}"


def _with_game_backups(saves: tuple[Path, ...]) -> list[Path]:
    """Detection already walks ``backup/`` folders; add any copy it did not list, never twice."""
    found: list[Path] = []
    seen: set[str] = set()
    for save in saves:
        for candidate in (save, save.parent / GAME_BACKUP_DIR / SAVE_FILE_NAME):
            key = str(candidate.absolute()).casefold()
            if key not in seen and candidate.is_file():
                seen.add(key)
                found.append(candidate)
    return found


def _copy(source: Path, target: Path) -> Copied:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    data = target.read_bytes()
    if data != source.read_bytes():
        raise RuntimeError(f"copy of {source} does not match the original")
    return Copied(source, target, len(data), hashlib.sha256(data).hexdigest())


def _copy_saves(saves: list[Path], dest: Path) -> list[Copied]:
    copies: list[Copied] = []
    names: set[str] = set()
    for save in saves:
        name = _copy_name(save)
        if name in names:
            name = f"{save.parent.parent.name}.{name}"
        names.add(name)
        copies.append(_copy(save, dest / "saves" / name))
    return copies


def _mods_root(snapshot: InstallSnapshot) -> Path | None:
    if snapshot.primary_mods_dir is not None:
        return snapshot.primary_mods_dir
    return snapshot.workshop_dirs[0] if snapshot.workshop_dirs else None


def _write_manifest(
    dest: Path, saves: list[Copied], state: Copied | None, snapshot: InstallSnapshot
) -> None:
    manifest = {
        "made_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mods_root": str(_mods_root(snapshot)) if _mods_root(snapshot) else None,
        "mod_roots": [str(path) for path in snapshot.mod_roots],
        "saves": [copied.record() for copied in saves],
        "state": state.record() if state is not None else None,
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")


def _print_env(dest: Path, state: Copied | None, snapshot: InstallSnapshot) -> None:
    mods_root = _mods_root(snapshot)
    print(f"DDM_SAVE_CORPUS={dest / 'saves'}")
    print(f"DDM_STATE_CORPUS={state.copy if state is not None else ''}")
    print(f"DDM_MODS_ROOT={mods_root if mods_root is not None else ''}")


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-dir", help="the DD Manager Data folder (the app's own override)")
    parser.add_argument("--state", help="an explicit mod_state.json to copy instead")
    parser.add_argument("--dest", default=str(DEFAULT_DEST), help="target folder (default .corpus)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    env = Environment.from_host()
    paths = resolve_app_paths(
        frozen=False,
        executable=Path(sys.executable),
        package_init=Path(src.__file__),
        env=env,
        override=Path(args.data_dir) if args.data_dir else None,
    )
    state_path = Path(args.state) if args.state else paths.state_file
    manual, mods_path = _state_hints(state_path) if state_path.is_file() else (ManualPaths(), None)
    snapshot = InstallDetector(env).detect(manual, mods_path)
    dest = Path(args.dest).absolute()
    saves = _copy_saves(_with_game_backups(snapshot.save_files), dest)
    state = _copy(state_path, dest / "state" / "mod_state.json") if state_path.is_file() else None
    _write_manifest(dest, saves, state, snapshot)
    for copied in saves:
        print(f"copied {copied.source} -> {copied.copy.name} ({copied.size} bytes)")
    if state is None:
        print(f"note: no mod_state.json at {state_path}; pass --state <file> or --data-dir <dir>")
    else:
        print(f"copied {state.source} -> state/{state.copy.name} ({state.size} bytes)")
    print(f"{len(saves)} saves, originals untouched; manifest in {dest / 'manifest.json'}")
    _print_env(dest, state, snapshot)
    return 0 if saves else 1


if __name__ == "__main__":
    raise SystemExit(main())
