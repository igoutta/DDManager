"""Install detection: Steam/GOG game folders, mod roots and saves.

The pure parsing helpers live in :mod:`src.services.steam_locations` and
:mod:`src.services.save_discovery` and are re-exported here.  ``InstallDetector.detect`` reads
the registry, the library VDFs and the ACF manifests once per call.
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from src.core.findings import Finding
from src.services.environment import Environment, Hive
from src.services.save_discovery import (
    discover_save_files,
    order_save_candidates,
)
from src.services.steam_locations import (
    DD_GAME_DIR_NAMES,
    DD_GAME_NAME,
    STEAM_APP_ID,
    is_steam_cloud_path,
    is_workshop_content_path,
    parse_appworkshop_acf,
    parse_libraryfolders_vdf,
    path_key,
    steam_install_roots,
    steam_library_roots,
    unique_paths,
    workshop_id_for_folder,
    workshop_manifest_paths,
)

__all__ = [
    "DD_GAME_DIR_NAMES",
    "DD_GAME_NAME",
    "STEAM_APP_ID",
    "InstallDetector",
    "InstallSnapshot",
    "ManualPaths",
    "candidate_game_folders",
    "candidate_local_mod_folders",
    "candidate_mod_folders",
    "candidate_workshop_mod_folders",
    "companion_mod_folders",
    "detect_best_mod_folder",
    "discover_save_files",
    "first_valid_manual_path",
    "gog_game_roots",
    "is_steam_cloud_path",
    "is_workshop_content_path",
    "order_save_candidates",
    "parse_appworkshop_acf",
    "parse_libraryfolders_vdf",
    "steam_install_roots",
    "steam_library_roots",
    "workshop_id_for_folder",
]

log = logging.getLogger(__name__)

_GOG_KEYS = (
    (Hive.HKLM, r"Software\GOG.com\Games"),
    (Hive.HKLM, r"Software\WOW6432Node\GOG.com\Games"),
    (Hive.HKCU, r"Software\GOG.com\Games"),
)
_GOG_FIXED_BASES = (
    Path(r"C:\GOG Games"),
    Path(r"C:\Program Files (x86)\GOG Galaxy\Games"),
    Path(r"C:\Program Files\GOG Galaxy\Games"),
)


def _is_dd1_game_name(game_name: str | None) -> bool:
    if not game_name:
        return False
    folded = game_name.casefold().strip()
    return folded.startswith("darkest dungeon") and " ii" not in folded and " 2" not in folded


def _is_dd_folder_name(path: Path) -> bool:
    return path.name.casefold() in {name.casefold() for name in DD_GAME_DIR_NAMES}


def _gog_registry_roots(env: Environment) -> list[Path]:
    roots: list[Path] = []
    for hive, key in _GOG_KEYS:
        for child in env.registry.subkeys(hive, key):
            entry = f"{key}\\{child}"
            value = env.registry.read_value(hive, entry, "path")
            if not value or not Path(value).is_dir():
                continue
            name = env.registry.read_value(hive, entry, "gameName")
            if _is_dd1_game_name(name) or _is_dd_folder_name(Path(value)):
                roots.append(Path(value))
    return roots


def gog_game_roots(env: Environment) -> list[Path]:
    """GOG installs: registry (DD1 only) and defaults."""
    if not env.is_windows:
        return []
    roots = _gog_registry_roots(env)
    for base in _GOG_FIXED_BASES:
        roots.extend(base / name for name in DD_GAME_DIR_NAMES if (base / name).is_dir())
    return unique_paths(roots)


def candidate_game_folders(libraries: Sequence[Path], gog_roots: Sequence[Path]) -> list[Path]:
    """``<library>/steamapps/common/<name>`` then GOG roots that exist."""
    found = [
        library / "steamapps" / "common" / name
        for library in libraries
        for name in DD_GAME_DIR_NAMES
    ]
    found.extend(gog_roots)
    return unique_paths(path for path in found if path.is_dir())


def candidate_local_mod_folders(game_folders: Sequence[Path]) -> list[Path]:
    """``<game>/mods`` folders that exist."""
    return unique_paths(root / "mods" for root in game_folders if (root / "mods").is_dir())


def candidate_workshop_mod_folders(libraries: Sequence[Path]) -> list[Path]:
    """``<library>/steamapps/workshop/content/262060`` folders that exist."""
    found = (library / "steamapps" / "workshop" / "content" / STEAM_APP_ID for library in libraries)
    return unique_paths(path for path in found if path.is_dir())


def first_valid_manual_path(manual: Path | None, candidates: Sequence[Path]) -> Path | None:
    """The manual folder when it exists, else the first candidate."""
    if manual is not None and manual.is_dir():
        return manual
    return candidates[0] if candidates else None


def _subdirectories(path: Path) -> list[Path]:
    try:
        return [entry for entry in path.iterdir() if entry.is_dir()]
    except OSError as exc:
        log.debug("cannot list %s: %s", path, exc)
        return []


def candidate_mod_folders(
    current: Path | None, workshop: Sequence[Path], local: Sequence[Path]
) -> list[Path]:
    """Current (first), workshop, local; keeps folders holding a subfolder."""
    candidates = [*workshop, *local]
    if current is not None:
        candidates.insert(0, current)
    return unique_paths(path for path in candidates if path.is_dir() and _subdirectories(path))


def detect_best_mod_folder(current: Path | None, candidates: Sequence[Path]) -> Path | None:
    """The current folder if it exists, else the one with most subfolders."""
    if current is not None and current.is_dir():
        return current
    if not candidates:
        return None
    return max(candidates, key=lambda path: len(_subdirectories(path)))


def companion_mod_folders(
    primary: Path | None, libraries: Sequence[Path], game_roots: Sequence[Path]
) -> list[Path]:
    """Workshop and game ``mods`` folders besides ``primary``.

    Per library the workshop folder comes first, then ``common/<each DD folder name>/mods``;
    GOG/manual game roots add ``<root>/mods`` (documented extension).
    """
    found: list[Path] = []
    for library in libraries:
        found.append(library / "steamapps" / "workshop" / "content" / STEAM_APP_ID)
        found.extend(library / "steamapps" / "common" / name / "mods" for name in DD_GAME_DIR_NAMES)
    found.extend(root / "mods" for root in game_roots)
    primary_key = None if primary is None else path_key(primary)
    return unique_paths(path for path in found if path.is_dir() and path_key(path) != primary_key)


@dataclass(frozen=True, slots=True)
class ManualPaths:
    """Folders the user chose by hand; each wins over detection when it exists."""

    game_root: Path | None = None
    local_mods: Path | None = None
    workshop_mods: Path | None = None


@dataclass(frozen=True, slots=True)
class InstallSnapshot:
    """Everything one detection pass learned."""

    steam_roots: tuple[Path, ...]
    libraries: tuple[Path, ...]
    game_roots: tuple[Path, ...]
    local_mod_dirs: tuple[Path, ...]
    workshop_dirs: tuple[Path, ...]
    primary_mods_dir: Path | None
    mod_roots: tuple[Path, ...]
    acf_files: tuple[Path, ...]
    save_files: tuple[Path, ...]
    findings: tuple[Finding, ...]


def _manual_first(manual: Path | None, found: Iterable[Path]) -> list[Path]:
    wanted = [manual] if manual is not None and manual.is_dir() else []
    return unique_paths([*wanted, *found])


class InstallDetector:
    """Locates the game, the mod folders and the saves on one host."""

    def __init__(self, env: Environment) -> None:
        self._env = env

    def detect(self, manual: ManualPaths, current_mods_path: Path | None) -> InstallSnapshot:
        steam_roots = steam_install_roots(self._env)
        libraries = steam_library_roots(steam_roots)
        game_roots = _manual_first(
            manual.game_root, candidate_game_folders(libraries, gog_game_roots(self._env))
        )
        local_dirs = _manual_first(manual.local_mods, candidate_local_mod_folders(game_roots))
        workshop_dirs = _manual_first(
            manual.workshop_mods, candidate_workshop_mod_folders(libraries)
        )
        primary = detect_best_mod_folder(
            current_mods_path, candidate_mod_folders(current_mods_path, workshop_dirs, local_dirs)
        )
        companions = companion_mod_folders(primary, libraries, game_roots)
        manual_extra = [d for d in (*workshop_dirs, *local_dirs) if d.is_dir()]
        roots = unique_paths([*([primary] if primary else []), *companions, *manual_extra])
        return InstallSnapshot(
            steam_roots=tuple(steam_roots),
            libraries=tuple(libraries),
            game_roots=tuple(game_roots),
            local_mod_dirs=tuple(local_dirs),
            workshop_dirs=tuple(workshop_dirs),
            primary_mods_dir=primary,
            mod_roots=tuple(roots),
            acf_files=tuple(workshop_manifest_paths(libraries)),
            save_files=tuple(discover_save_files(self._env, steam_roots, libraries)),
            findings=() if roots else (_no_mods_finding(),),
        )


def _no_mods_finding() -> Finding:
    return Finding.warning("detect.no_mods_root", "No Darkest Dungeon mods folder was found.")
