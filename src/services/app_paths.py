"""The only data-directory resolver.

Precedence: explicit override argument, then ``DDMANAGER_DATA_DIR``, then a portable
``DD Manager Data`` folder next to the executable (frozen) or at the repo root (source), then the
per-user data directory.  The working directory and ``sys.argv`` are never consulted.
"""

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from src.services.environment import Environment
from src.services.errors import DataDirNotWritableError

DATA_DIR_NAME: Final = "DD Manager Data"
ENV_OVERRIDE: Final = "DDMANAGER_DATA_DIR"


class DataDirMode(StrEnum):
    OVERRIDE = "override"
    PORTABLE_FROZEN = "portable_frozen"
    PORTABLE_SOURCE = "portable_source"
    USER = "user"


@dataclass(frozen=True, slots=True)
class AppPaths:
    data_dir: Path
    mode: DataDirMode
    anchor: Path | None
    reason: str

    @property
    def state_file(self) -> Path:
        return self.data_dir / "mod_state.json"

    @property
    def state_backup_file(self) -> Path:
        return self.data_dir / "mod_state.backup.json"

    @property
    def pre_upgrade_state_file(self) -> Path:
        return self.data_dir / "mod_state.pre-0.3.0.json"

    def corrupt_state_file(self, timestamp: str) -> Path:
        return self.data_dir / f"mod_state.corrupt.{timestamp}.json"

    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def ui_settings_file(self) -> Path:
        return self.data_dir / "ui.ini"

    @property
    def lock_file(self) -> Path:
        return self.data_dir / "ddmanager.lock"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    @property
    def rules_dir(self) -> Path:
        return self.data_dir / "rules"

    @property
    def user_rules_file(self) -> Path:
        return self.rules_dir / "rules.json"

    @property
    def plugins_dir(self) -> Path:
        return self.data_dir / "plugins"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def mod_info_cache_file(self) -> Path:
        return self.cache_dir / "mod_info.v1.json"

    @property
    def icon_cache_dir(self) -> Path:
        """The 0.2.x folder name, kept so an existing cache keeps working."""
        return self.data_dir / "icon_cache"

    @property
    def crash_log(self) -> Path:
        """The 0.2.x file name, kept."""
        return self.data_dir / "startup_crash.log"

    def ensure(self) -> None:
        """Create the data directory tree (called by the composition root, never at import)."""
        for directory in (
            self.data_dir,
            self.logs_dir,
            self.backups_dir,
            self.profiles_dir,
            self.rules_dir,
            self.plugins_dir,
            self.cache_dir,
            self.icon_cache_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def find_repo_root(package_init: Path) -> Path | None:
    """The repo root when ``package_init`` is ``<root>/src/__init__.py`` of a source checkout."""
    root = package_init.absolute().parents[1]
    if (root / "pyproject.toml").is_file() and (root / "src" / "__init__.py").is_file():
        return root
    return None


def user_data_dir(env: Environment) -> Path:
    """The per-user data directory of the platform."""
    if env.is_windows:
        base = env.env_path("LOCALAPPDATA") or env.home / "AppData" / "Local"
        return base / "DD Manager"
    if env.is_macos:
        return env.home / "Library" / "Application Support" / "DD Manager"
    base = env.env_path("XDG_DATA_HOME") or env.home / ".local" / "share"
    return base / "dd-manager"


def probe_writable(directory: Path) -> bool:
    """Really create and delete a temp file (``os.access`` lies on Windows ACLs)."""
    try:
        fd, name = tempfile.mkstemp(prefix=".ddm-probe-", dir=directory)
    except OSError:
        return False
    os.close(fd)
    Path(name).unlink(missing_ok=True)
    return True


def _portable(
    anchor: Path, mode: DataDirMode, is_writable: Callable[[Path], bool]
) -> AppPaths | None:
    target = anchor / DATA_DIR_NAME
    if target.is_dir():
        if not is_writable(target):
            raise DataDirNotWritableError(
                f"The data folder {target} exists but is not writable.", path=str(target)
            )
        return AppPaths(target, mode, anchor, f"existing portable folder next to {anchor}")
    if is_writable(anchor):
        return AppPaths(target, mode, anchor, f"new portable folder in {anchor}")
    return None


def resolve_app_paths(
    *,
    frozen: bool,
    executable: Path,
    package_init: Path,
    env: Environment,
    override: Path | None = None,
    is_writable: Callable[[Path], bool] = probe_writable,
) -> AppPaths:
    """Pick the data directory (see the module docstring for the precedence)."""
    if override is not None:
        return AppPaths(override.absolute(), DataDirMode.OVERRIDE, None, "explicit argument")
    from_env = env.env_path(ENV_OVERRIDE)
    if from_env is not None:
        return AppPaths(from_env.absolute(), DataDirMode.OVERRIDE, None, f"{ENV_OVERRIDE} variable")
    if frozen:
        mode, anchor = DataDirMode.PORTABLE_FROZEN, executable.absolute().parent
    else:
        mode, anchor = DataDirMode.PORTABLE_SOURCE, find_repo_root(package_init)
    portable = None if anchor is None else _portable(anchor, mode, is_writable)
    if portable is not None:
        return portable
    reason = "no portable anchor" if anchor is None else f"{anchor} is not writable"
    return AppPaths(user_data_dir(env), DataDirMode.USER, None, reason)
