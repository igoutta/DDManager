"""Every window action, built once from specs and shared by the toolbar, menus and buttons."""

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup

from src.core.load_order import MoveOp, PriorityDirection
from src.ui.controller import MainController
from src.ui.i18n import Translator
from src.ui.theme.tokens import DENSITY
from src.ui.widgets.actions import ActionSpec, IconSet, make_action, retranslate_action

if TYPE_CHECKING:
    from src.ui.widgets.main_window import MainWindow

WIDGET = Qt.ShortcutContext.WidgetWithChildrenShortcut
LANGUAGES = ("en", "zh_CN", "pt_PT", "es_ES")
PRIORITY_KEYS = ("prio_first", "prio_last")
DENSITY_SLUGS = {mode: mode.lower().replace(" ", "_") for mode in DENSITY}


class ActionHub:
    """Builds the ``QAction`` objects (``act_<key>``) and keeps their enabled state current."""

    def __init__(self, window: MainWindow, translator: Translator, icons: IconSet) -> None:
        self._w = window
        self._tr = translator
        self.actions: dict[str, QAction] = {}
        self.specs: list[ActionSpec] = []
        for spec in self._specs():
            self.specs.append(spec)
            self.actions[spec.key] = make_action(spec, window, translator.tr, icons)
        self._group("density", [f"density_{slug}" for slug in DENSITY_SLUGS.values()])
        self._group("language", [f"lang_{c}" for c in LANGUAGES])
        self._group("priority", list(PRIORITY_KEYS))

    def _group(self, name: str, keys: Sequence[str]) -> None:
        group = QActionGroup(self._w)
        group.setObjectName(f"group_{name}")
        group.setExclusive(True)
        for key in keys:
            group.addAction(self.actions[key])

    def __getitem__(self, key: str) -> QAction:
        return self.actions[key]

    def retranslate(self) -> None:
        for action in self.actions.values():
            retranslate_action(action, self._tr.tr)

    # ------------------------------------------------------------------ specs

    def _specs(self) -> list[ActionSpec]:
        return [*self._file_specs(), *self._edit_specs(), *self._view_specs(), *self._help_specs()]

    def _file_specs(self) -> list[ActionSpec]:
        w, c = self._w, self._w.controller
        return [
            ActionSpec("rescan", "rescan", c.rescan, ("F5",)),
            ActionSpec("backup", "backup", c.backup_save, ("Ctrl+B",)),
            ActionSpec("patch", "patch", c.patch_save, ("Ctrl+Shift+P",), danger=True),
            ActionSpec("profiles", "profiles", w.open_profile_manager, ("Ctrl+P",)),
            ActionSpec("choose_save", "folder", c.settings.choose_save_file),
            ActionSpec("choose_mods", "folder", c.settings.choose_mods_folder),
            ActionSpec("open_save_folder", "folder", c.open_save_folder),
            ActionSpec("open_local_mods", "folder", c.open_local_mods_folder),
            ActionSpec("launch_game", "enable", c.launch_game),
            ActionSpec("quit", "disable", w.quit_app, ("Ctrl+Q",)),
        ]

    def _edit_specs(self) -> list[ActionSpec]:
        w, c = self._w, self._w.controller

        def move(op: MoveOp) -> Callable[[], None]:
            return lambda: w.move_selection(op)

        return [
            ActionSpec("undo", "undo", c.undo, ("Ctrl+Z",)),
            ActionSpec("redo", "redo", c.redo, ("Ctrl+Y", "Ctrl+Shift+Z")),
            ActionSpec("find", "find", w.focus_search, ("Ctrl+F",)),
            ActionSpec("enable", "enable", w.enable_selection, ("Ctrl+Right",), WIDGET),
            ActionSpec("disable", "disable", w.disable_selection, ("Ctrl+Left", "Delete"), WIDGET),
            ActionSpec("top", "top", move(MoveOp.TOP), ("Ctrl+Home",), WIDGET),
            ActionSpec("up", "up", move(MoveOp.UP), ("Ctrl+Up",), WIDGET),
            ActionSpec("down", "down", move(MoveOp.DOWN), ("Ctrl+Down",), WIDGET),
            ActionSpec("bottom", "bottom", move(MoveOp.BOTTOM), ("Ctrl+End",), WIDGET),
            ActionSpec("sort", "sort", c.auto_sort, ("Ctrl+Shift+A",)),
            ActionSpec("validate", "check", w.run_validate, ("F7",)),
            ActionSpec("open_mod_folder", "folder", w.open_mod_folder),
            ActionSpec("open_mod_page", "link", w.open_mod_page),
            ActionSpec("forget_missing", "warning", w.forget_missing),
        ]

    def _view_specs(self) -> list[ActionSpec]:
        w, c = self._w, self._w.controller
        specs = [ActionSpec("health", "warning", w.toggle_health, ("F8",), checkable=True)]
        specs += [
            ActionSpec(f"density_{slug}", "check", _bind(c.set_density, mode), checkable=True)
            for mode, slug in DENSITY_SLUGS.items()
        ]
        specs += [
            ActionSpec(f"lang_{code}", "check", _bind(c.set_language, code), checkable=True)
            for code in LANGUAGES
        ]
        specs += [
            ActionSpec(
                "prio_first", "up", _priority(c, PriorityDirection.FIRST_WINS), checkable=True
            ),
            ActionSpec(
                "prio_last", "down", _priority(c, PriorityDirection.LAST_WINS), checkable=True
            ),
            ActionSpec("prio_verified", "check", w.toggle_verified, checkable=True),
        ]
        return specs

    def _help_specs(self) -> list[ActionSpec]:
        w = self._w
        return [
            ActionSpec("shortcuts", "help", w.open_shortcuts, ("F1",)),
            ActionSpec("about", "info", w.open_about),
        ]


def _bind(func: Callable[[str], None], value: str) -> Callable[[], None]:
    return lambda: func(value)


def _priority(controller: MainController, direction: PriorityDirection) -> Callable[[], None]:
    def apply() -> None:
        presenter = controller.settings
        presenter.set_priority(direction, verified=presenter.priority().verified)

    return apply
