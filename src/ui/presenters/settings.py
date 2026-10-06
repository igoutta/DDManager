"""Settings presenter: priority direction, language, density and the two path pickers."""

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

from src.core.load_order import PriorityDirection, PrioritySetting
from src.services.settings_repo import Settings
from src.ui.theme.tokens import DENSITY

if TYPE_CHECKING:
    from src.ui.controller import MainController


class SettingsPresenter(QObject):
    def __init__(self, controller: MainController) -> None:
        super().__init__(controller)
        self._c = controller
        self._settings: Settings = controller.services.initial_settings

    # ------------------------------------------------------------------ load / save

    def load(self) -> Settings:
        """The settings file as it is now (also refreshes the cached value)."""
        self._settings, _findings = self._c.services.settings.load()
        return self._settings

    def current(self) -> Settings:
        return self._settings

    def save(self, settings: Settings) -> None:
        try:
            self._c.services.settings.save(settings)
        except OSError as exc:
            self._c.post("ui.notice.settings_failed", "error", error=str(exc))
            return
        self._settings = settings

    # ------------------------------------------------------------------ individual settings

    def priority(self) -> PrioritySetting:
        return self._settings.priority

    def set_priority(self, direction: PriorityDirection, *, verified: bool) -> None:
        self.save(replace(self._settings, priority=PrioritySetting(direction, verified)))
        self._c.priority_changed()

    def language(self) -> str:
        return self._c.language()

    def set_language(self, code: str) -> None:
        self._c.set_language(code)

    def density(self) -> str:
        mode = self._c.density()
        return mode if mode in DENSITY else "Comfortable"

    def set_density(self, mode: str) -> None:
        if mode in DENSITY:
            self._c.set_density(mode)

    # ------------------------------------------------------------------ pickers

    def choose_save_file(self) -> None:
        start = self._c.save_path()
        prompter = self._c.prompter
        picked = prompter.pick_save_file(start.parent if start else None) if prompter else None
        if picked is not None:
            self._c.use_save(picked)

    def choose_mods_folder(self) -> None:
        settings = self._c.state_settings()
        start = Path(settings.mods_path) if settings.mods_path else None
        prompter = self._c.prompter
        picked = prompter.pick_folder(start) if prompter else None
        if picked is not None:
            self._c.set_mods_path(picked)
