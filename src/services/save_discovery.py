"""Finding ``persist.game.json`` files on disk."""

import logging
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from src.services.environment import Environment
from src.services.steam_locations import STEAM_APP_ID, unique_paths

log = logging.getLogger(__name__)

SAVE_FILE_NAME: Final = "persist.game.json"
_ONEDRIVE_VARS: Final = ("USERPROFILE", "OneDrive", "OneDriveConsumer", "OneDriveCommercial")


def _walk_for_saves(directory: Path) -> list[Path]:
    """Every exact ``persist.game.json`` below ``directory`` (links are not followed)."""
    found: list[Path] = []
    if not directory.is_dir():
        return found

    def on_error(exc: OSError) -> None:
        log.debug("save discovery skipped %s: %s", exc.filename, exc)

    for root, dirs, files in directory.walk(on_error=on_error, follow_symlinks=False):
        dirs.sort()
        if SAVE_FILE_NAME in files:
            found.append(root / SAVE_FILE_NAME)
    return found


def _steam_userdata_saves(steam_roots: Sequence[Path]) -> list[Path]:
    found: list[Path] = []
    for steam_root in steam_roots:
        userdata = steam_root / "userdata"
        try:
            users = sorted(entry for entry in userdata.iterdir() if entry.is_dir())
        except OSError as exc:
            log.debug("cannot list %s: %s", userdata, exc)
            continue
        for user in users:
            found.extend(_walk_for_saves(user / STEAM_APP_ID / "remote"))
    return found


def _proton_saves(libraries: Sequence[Path]) -> list[Path]:
    found: list[Path] = []
    for library in libraries:
        prefix = library / "steamapps" / "compatdata" / STEAM_APP_ID / "pfx" / "drive_c"
        found.extend(_walk_for_saves(prefix / "users" / "steamuser" / "Documents" / "Darkest"))
    return found


def windows_documents_roots(env: Environment) -> list[Path]:
    """Documents folders (profile, OneDrive, ``~/Documents``, known folder)."""
    candidates = [base / "Documents" for name in _ONEDRIVE_VARS if (base := env.env_path(name))]
    candidates.append(env.home / "Documents")
    if env.known_documents_dir is not None:
        candidates.append(env.known_documents_dir)
    return unique_paths(candidate for candidate in candidates if candidate.is_dir())


def _platform_saves(env: Environment, libraries: Sequence[Path]) -> list[Path]:
    if env.is_windows:
        return [
            save
            for documents in windows_documents_roots(env)
            for save in _walk_for_saves(documents / "Darkest")
        ]
    if env.is_linux:
        local = env.home / ".local" / "share" / "Red Hook Studios" / "Darkest"
        return [*_proton_saves(libraries), *_walk_for_saves(local)]
    support = env.home / "Library" / "Application Support" / "Red Hook Studios" / "Darkest"
    return _walk_for_saves(support)


def discover_save_files(
    env: Environment, steam_roots: Sequence[Path], libraries: Sequence[Path]
) -> list[Path]:
    """Steam Cloud copies first, then the platform's local save folders."""
    found = [*_steam_userdata_saves(steam_roots), *_platform_saves(env, libraries)]
    return unique_paths(found)


def order_save_candidates(
    selected: Path | None, last: Path | None, detected: Iterable[Path]
) -> list[Path]:
    """Selected, last, then detected; existing files only, no duplicates."""
    wanted = [path for path in (selected, last) if path is not None]
    return unique_paths(path for path in [*wanted, *detected] if path.is_file())
