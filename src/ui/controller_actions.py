"""Platform actions of the controller: open folders and pages, launch the game."""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.ids import ModId
from src.services import platform_actions
from src.services.errors import ServiceError

if TYPE_CHECKING:
    from src.ui.controller import MainController


class PlatformFlows:
    def __init__(self, controller: MainController) -> None:
        self._c = controller

    def _guarded(self, action: Callable[[], object]) -> None:
        try:
            action()
        except ServiceError as exc:
            self._c.post("ui.notice.action_failed", "error", error=exc.message)

    def open_path(self, path: Path) -> None:
        self._guarded(lambda: platform_actions.open_folder(path, self._c.services.env))

    def open_mod_folder(self, mod_id: ModId) -> None:
        info = self._c.mods().get(mod_id)
        if info is not None:
            self.open_path(Path(info.path))

    def open_save_folder(self) -> None:
        save = self._c.save_path()
        if save is not None:
            self.open_path(save.parent)

    def open_workshop_page(self, mod_id: ModId) -> None:
        url = self._c.page_url(mod_id)
        if url:
            self._guarded(lambda: platform_actions.open_url(url))

    def launch_game(self) -> None:
        install = self._c.install()
        if install is not None:
            self._guarded(lambda: platform_actions.launch_game(install, self._c.services.env))

    def open_local_mods_folder(self) -> None:
        install = self._c.install()
        if install is not None and install.local_mod_dirs:
            self.open_path(install.local_mod_dirs[0])

    def open_backup_folder(self) -> None:
        save = self._c.save_path()
        if save is not None:
            self.open_path(self._c.services.backups.slot_dir(save))
