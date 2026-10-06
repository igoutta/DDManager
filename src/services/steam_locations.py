"""Steam installs, libraries, ACF manifests and workshop paths (``paths.py:14-121``)."""

import logging
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from src.services.environment import Environment, Hive

log = logging.getLogger(__name__)

STEAM_APP_ID: Final = "262060"
DD_GAME_NAME: Final = "DarkestDungeon"
DD_GAME_DIR_NAMES: Final = ("DarkestDungeon", "Darkest Dungeon")

_LIBRARY_PATH_RE: Final = re.compile(r'"path"\s+"([^"]+)"')
_ACF_ITEM_RE: Final = re.compile(
    r'"(?P<id>\d+)"\s*\{[^{}]*?"timeupdated"\s*"(?P<ts>\d+)"',
    re.DOTALL,
)
_STEAM_KEY: Final = r"Software\Valve\Steam"
_STEAM_WOW_KEY: Final = r"Software\WOW6432Node\Valve\Steam"
_LINUX_STEAM_DIRS: Final[tuple[tuple[str, ...], ...]] = (
    (".steam", "steam"),
    (".steam", "root"),
    (".local", "share", "Steam"),
    (".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam"),
    (".var", "app", "com.valvesoftware.Steam", "data", "Steam"),
)


def path_key(path: Path) -> str:
    """Identity of a path for de-duplication: casefolded absolute path (no link resolution)."""
    return str(path.absolute()).casefold()


def unique_paths(paths: Iterable[Path]) -> list[Path]:
    """``paths.py:27-35``: drop duplicates by :func:`path_key`, keeping the first occurrence."""
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = path_key(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _registry_steam_roots(env: Environment) -> list[Path]:
    lookups = (
        (Hive.HKCU, _STEAM_KEY, "SteamPath"),
        (Hive.HKCU, _STEAM_KEY, "InstallPath"),
        (Hive.HKLM, _STEAM_KEY, "InstallPath"),
        (Hive.HKLM, _STEAM_WOW_KEY, "InstallPath"),
    )
    values = (env.registry.read_value(hive, key, name) for hive, key, name in lookups)
    return [Path(value) for value in values if value and Path(value).is_dir()]


def _windows_steam_roots(env: Environment) -> list[Path]:
    roots = _registry_steam_roots(env)
    for name in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        base = env.env_path(name)
        if base is not None and (base / "Steam").is_dir():
            roots.append(base / "Steam")
    default = Path(r"C:\Program Files (x86)\Steam")
    if default.is_dir():
        roots.append(default)
    return roots


def steam_install_roots(env: Environment) -> list[Path]:
    """``paths.py:38-79``: existing Steam install folders, registry first, de-duplicated."""
    if env.is_windows:
        return unique_paths(_windows_steam_roots(env))
    if env.is_macos:
        return unique_paths(
            [p for p in (env.home / "Library" / "Application Support" / "Steam",) if p.is_dir()]
        )
    candidates = (env.home.joinpath(*parts) for parts in _LINUX_STEAM_DIRS)
    return unique_paths(candidate for candidate in candidates if candidate.is_dir())


def parse_libraryfolders_vdf(text: str) -> list[str]:
    """``paths.py:116-117``: every ``"path"`` value, with ``\\\\`` unescaped to ``\\``."""
    return [match.group(1).replace("\\\\", "\\") for match in _LIBRARY_PATH_RE.finditer(text)]


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        log.debug("cannot read %s: %s", path, exc)
        return None


def _vdf_libraries(steam_root: Path) -> list[Path]:
    text = _read_text(steam_root / "steamapps" / "libraryfolders.vdf")
    if text is None:
        return []
    libraries: list[Path] = []
    for raw in parse_libraryfolders_vdf(text):
        try:
            library = Path(raw).expanduser()
        except RuntimeError as exc:
            log.debug("cannot expand library path %r: %s", raw, exc)
            continue
        if library.is_dir():
            libraries.append(library)
    return libraries


def steam_library_roots(steam_roots: Sequence[Path]) -> list[Path]:
    """``paths.py:104-121``: each Steam root followed by the libraries its VDF lists."""
    libraries: list[Path] = []
    for steam_root in steam_roots:
        libraries.append(steam_root)
        libraries.extend(_vdf_libraries(steam_root))
    return unique_paths(libraries)


def parse_appworkshop_acf(text: str) -> dict[str, str]:
    """``dd2.py:3319-3341``: workshop item id -> ``timeupdated``; the first occurrence wins."""
    updates: dict[str, str] = {}
    for match in _ACF_ITEM_RE.finditer(text):
        updates.setdefault(match.group("id"), match.group("ts"))
    return updates


def workshop_manifest_paths(libraries: Sequence[Path]) -> list[Path]:
    """``dd2.py:3298-3314``: ``appworkshop_262060.acf`` files that exist, de-duplicated."""
    manifest = f"appworkshop_{STEAM_APP_ID}.acf"
    found = (library / "steamapps" / "workshop" / manifest for library in libraries)
    return unique_paths(candidate for candidate in found if candidate.is_file())


def read_workshop_update_times(manifests: Sequence[Path]) -> dict[str, str]:
    """``dd2.py:3316-3341``: merge the ACF files; the first file that names an item wins."""
    updates: dict[str, str] = {}
    for manifest in manifests:
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.debug("cannot read %s: %s", manifest, exc)
            continue
        for item_id, stamp in parse_appworkshop_acf(text).items():
            updates.setdefault(item_id, stamp)
    return updates


def _find_segments(parts: Sequence[str], wanted: Sequence[str]) -> int:
    """Index of the first exact run of ``wanted`` in ``parts`` (casefolded), or ``-1``."""
    folded = [part.casefold() for part in parts]
    size = len(wanted)
    for index in range(len(folded) - size + 1):
        if folded[index : index + size] == list(wanted):
            return index
    return -1


def is_workshop_content_path(path: Path, app_id: str = STEAM_APP_ID) -> bool:
    """True when ``path`` is, or lies under, ``steamapps/workshop/content/<app_id>``.

    Whole path segments are compared (``paths.py:14-24`` did a substring test and so also
    matched ``content/2620601``).
    """
    wanted = ("steamapps", "workshop", "content", app_id.casefold())
    return _find_segments(path.absolute().parts, wanted) >= 0


def is_steam_cloud_path(path: Path) -> bool:
    """True for ``.../userdata/<digits>/262060/remote/...``."""
    parts = [part.casefold() for part in path.absolute().parts]
    for index in range(len(parts) - 3):
        window = parts[index : index + 4]
        if (
            window[0] == "userdata"
            and window[1].isdigit()
            and window[2:] == [STEAM_APP_ID, "remote"]
        ):
            return True
    return False


def workshop_id_for_folder(path: Path, *, under_workshop: bool) -> str:
    """``dd2.py:3968-3985``: the workshop id a folder name encodes, ``""`` outside the workshop.

    Order: an all-digit folder name; else the first of the first two ``_`` parts with at least
    seven digits.  (The legacy final basename test repeated the first one and never fired.)
    """
    if not under_workshop:
        return ""
    name = path.name
    if name.isdigit():
        return name
    for part in name.split("_")[:2]:
        if part.isdigit() and len(part) >= 7:
            return part
    return ""
