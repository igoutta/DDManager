"""Paths presenter: the five state-file path settings, Browse / Auto / Clear, Auto Detect.

The five keys are the ``mod_state.json`` ones; saving writes them (and ``last_save_path`` with
the profile save) through :meth:`MainController.apply_settings` and rescans.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from PySide6.QtCore import QObject

from src.core.json_values import JsonValue
from src.services.detection import InstallSnapshot, ManualPaths
from src.services.ports import CancelToken
from src.ui.controller_scan import manual_paths, optional_path

if TYPE_CHECKING:
    from src.ui.controller import MainController

PATH_KEYS: Final = (
    "manual_game_root",
    "mods_path",
    "manual_local_mods_path",
    "manual_workshop_mods_path",
    "selected_profile_path",
)
FILE_KEYS: Final = frozenset({"selected_profile_path"})


@dataclass(frozen=True, slots=True)
class PathEntryVM:
    key: str
    label_key: str
    kind: Literal["dir", "file"]
    value: str


@dataclass(frozen=True, slots=True)
class DetectedPaths:
    """What one detection pass found, in the ``autodetect_summary`` shape."""

    game_root: str
    local_mods: str
    workshop_mods: str
    best_mods: str
    latest_save: str
    profile_count: int


def normalize_path_text(text: str) -> str:
    """``""`` for blank text, else the path with normalised separators."""
    stripped = text.strip()
    return str(Path(stripped)) if stripped else ""


def _first(paths: tuple[Path, ...]) -> str:
    return str(paths[0]) if paths else ""


def summarize(install: InstallSnapshot, latest: Path | None, profile_count: int) -> DetectedPaths:
    return DetectedPaths(
        game_root=_first(install.game_roots),
        local_mods=_first(install.local_mod_dirs),
        workshop_mods=_first(install.workshop_dirs),
        best_mods=str(install.primary_mods_dir) if install.primary_mods_dir else "",
        latest_save=str(latest) if latest else "",
        profile_count=profile_count,
    )


class PathsPresenter(QObject):
    def __init__(self, controller: MainController) -> None:
        super().__init__(controller)
        self._c = controller

    # ------------------------------------------------------------------ the editor

    def entries(self) -> tuple[PathEntryVM, ...]:
        """The five fields: the saved value, else the path the app is using right now."""
        saved = self._c.state_settings()
        current = self._current()
        return tuple(
            PathEntryVM(
                key,
                f"ui.paths.{key}",
                "file" if key in FILE_KEYS else "dir",
                str(getattr(saved, key) or current.get(key, "")),
            )
            for key in PATH_KEYS
        )

    def _current(self) -> dict[str, str]:
        install = self._c.install()
        save = self._c.save_path()
        if install is None:
            return {"selected_profile_path": str(save or "")}
        summary = summarize(install, save, 0)
        return {
            "manual_game_root": summary.game_root,
            "mods_path": summary.best_mods,
            "manual_local_mods_path": summary.local_mods,
            "manual_workshop_mods_path": summary.workshop_mods,
            "selected_profile_path": summary.latest_save,
        }

    def detected(self, key: str) -> str:
        """The automatic value of ``key`` (``Auto``): detection without any manual override."""
        services = self._c.services
        found = services.detector.detect(ManualPaths(), None)
        summary = summarize(found, services.slots.latest(found.save_files), 0)
        values = {
            "manual_game_root": summary.game_root,
            "mods_path": summary.best_mods,
            "manual_local_mods_path": summary.local_mods,
            "manual_workshop_mods_path": summary.workshop_mods,
            "selected_profile_path": summary.latest_save,
        }
        return normalize_path_text(values.get(key, ""))

    def browse(self, key: str, current: str) -> str | None:
        """Ask for a folder (or the save file) starting near ``current``; ``None`` if cancelled."""
        prompter = self._c.prompter
        if prompter is None:
            return None
        start = Path(normalize_path_text(current)) if current.strip() else None
        if key in FILE_KEYS:
            parent = start.parent if start is not None else None
            picked = prompter.pick_save_file(parent if parent and parent.is_dir() else None)
        else:
            picked = prompter.pick_folder(start if start is not None and start.is_dir() else None)
        return normalize_path_text(str(picked)) if picked is not None else None

    def save(self, values: Mapping[str, str]) -> None:
        """Store the five paths, then rescan with them."""
        c = self._c
        cleaned = {key: normalize_path_text(values.get(key, "")) for key in PATH_KEYS}
        updates: dict[str, JsonValue] = {}
        updates.update(cleaned)
        profile = cleaned["selected_profile_path"]
        if profile:
            updates["last_save_path"] = profile
        c.apply_settings(updates, rescan=True)
        mods = cleaned["mods_path"]
        if profile and Path(profile).is_file():
            c.post("status_manual_paths_profile", path=profile)
        elif mods:
            c.post("status_manual_paths_mods", path=mods)
        else:
            c.post("status_manual_paths")

    # ------------------------------------------------------------------ auto detect

    def auto_detect(self) -> None:
        """Detect again (honouring the manual paths), adopt the best mods folder and newest save."""
        c = self._c
        settings = c.state_settings()
        services = c.services
        manual = manual_paths(settings)
        current = optional_path(settings.mods_path)

        def task(_token: CancelToken) -> DetectedPaths:
            install = services.detector.detect(manual, current)
            latest = services.slots.latest(install.save_files)
            return summarize(install, latest, len(services.slots.slots(install.save_files)))

        c.run_task(task, self._detected, busy_key="ui.busy.detecting", key="detect")

    def _detected(self, found: DetectedPaths) -> None:
        c = self._c
        updates: dict[str, JsonValue] = {}
        if found.best_mods:
            updates["mods_path"] = found.best_mods
        if found.latest_save:
            updates["last_save_path"] = found.latest_save
        if updates:
            c.apply_settings(updates, rescan=bool(found.best_mods))
        self._report(found, found_anything=bool(updates))

    def _report(self, found: DetectedPaths, *, found_anything: bool) -> None:
        """The summary (or the "nothing found" help) as a message."""
        c = self._c
        prompter = c.prompter
        if not found_anything:
            if prompter is not None:
                prompter.info("auto_detect_nothing_found_body")
            else:
                c.post("nothing_found", "warning")
            return
        not_found = c.tr("not_found")
        params = {
            "game_root": found.game_root or not_found,
            "local_mods": found.local_mods or not_found,
            "workshop_mods": found.workshop_mods or not_found,
            "mod_text": found.best_mods or c.tr("no_mod_folder_found"),
            "save_text": found.latest_save or c.tr("no_save_file_found"),
            "profile_count": found.profile_count,
        }
        if prompter is not None:
            prompter.info("auto_detect_complete_body", **params)
        else:
            c.post("ui.notice.auto_detected", mods=params["mod_text"], save=params["save_text"])
