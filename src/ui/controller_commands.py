"""The controller's entry points behind the window actions: scans, settings, platform and save.

Each method is a one-liner into a flow (``ScanFlow``, ``PlatformFlows``, ``SaveFlows``) or a
small settings write; ``MainController`` derives from this class and creates the flows in its
``__init__``.  Keeping them here leaves ``controller.py`` with construction, publishing and edits.
"""

import dataclasses
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.ids import ModId
from src.core.json_values import JsonValue
from src.core.legacy_state import StateSettings
from src.ui.controller_core import ControllerCore

if TYPE_CHECKING:
    from src.ui.controller_actions import PlatformFlows
    from src.ui.controller_boot import ScanFlow
    from src.ui.controller_save import SaveFlows


class ControllerCommands(ControllerCore):
    _scan: ScanFlow
    _platform: PlatformFlows
    _flows: SaveFlows

    # ================================================================== start / scan

    def start(self) -> None:
        """First-run flow: validate the saved mods folder or detect one, then scan."""
        self.rescan()

    def rescan(self) -> None:
        self._scan.rescan()

    def reclassify(self) -> None:
        """Silently categorise unseen mods (never reorders) and refresh their tiers."""
        self._scan.reclassify()

    # ================================================================== slots / settings

    def use_save(self, path: Path) -> None:
        s = self._s
        s.save_path = path
        s.pending.settings.update({"selected_profile_path": str(path), "last_save_path": str(path)})
        record = self.services.backups.latest(path)
        s.last_backup = record.created if record else None
        self.schedule_save()
        self.emit_status()
        self.slotsChanged.emit()

    def set_mods_path(self, path: Path) -> None:
        self.apply_settings({"mods_path": str(path)}, rescan=True)

    def apply_settings(self, updates: Mapping[str, JsonValue], *, rescan: bool = False) -> None:
        """Write state-file settings now (dialogs with an explicit Save), then maybe rescan."""
        s = self._s
        s.pending.settings.update(updates)
        known = {f.name for f in dataclasses.fields(StateSettings)}
        text = {key: str(value) for key, value in updates.items() if key in known}
        settings = dataclasses.replace(s.doc.settings, **text)
        s.doc = dataclasses.replace(s.doc, settings=settings)
        self._sync.flush()
        if rescan:
            self.rescan()

    def set_language(self, code: str) -> None:
        self._s.pending.settings["language"] = code
        self.schedule_save()
        self.translator.set_language(code)

    def set_density(self, mode: str) -> None:
        self._s.pending.settings["view_mode"] = mode
        self.schedule_save()
        self.densityChanged.emit(mode)

    def density(self) -> str:
        return str(self._s.pending.settings.get("view_mode", self._s.doc.settings.view_mode))

    def language(self) -> str:
        return self.translator.language()

    # ================================================================== platform and save actions

    def open_path(self, path: Path) -> None:
        self._platform.open_path(path)

    def open_folder(self, mod_id: ModId) -> None:
        self._platform.open_mod_folder(mod_id)

    def open_save_folder(self) -> None:
        self._platform.open_save_folder()

    def open_workshop_page(self, mod_id: ModId) -> None:
        self._platform.open_workshop_page(mod_id)

    def launch_game(self) -> None:
        self._platform.launch_game()

    def open_local_mods_folder(self) -> None:
        self._platform.open_local_mods_folder()

    def open_backup_folder(self) -> None:
        self._platform.open_backup_folder()

    def backup_save(self) -> None:
        self._flows.backup()

    def patch_save(self) -> None:
        self._flows.patch()

    def patch_other_file(self) -> None:
        """Tools > Patch other file: pick any save file, then the usual patch preview."""
        self._flows.patch_other()

    def patch_latest_detected(self) -> None:
        """Tools > Patch latest detected: the newest detected save, confirmed first."""
        self._flows.patch_latest()
