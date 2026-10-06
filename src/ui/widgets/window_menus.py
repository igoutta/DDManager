"""The toolbar and the menu bar of the main window."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QMainWindow, QMenu, QSizePolicy, QToolBar, QWidget

from src.ui.i18n import Translator
from src.ui.widgets.window_actions import DENSITY_SLUGS, LANGUAGES, ActionHub


class WindowChrome:
    """Owns the toolbar, the slot combo and the menus, and retranslates their titles."""

    def __init__(self, window: QMainWindow, hub: ActionHub, translator: Translator) -> None:
        self._hub = hub
        self._tr = translator
        self.menus: dict[str, QMenu] = {}
        self.slot_combo = QComboBox(window)
        self.toolbar = self._toolbar(window)
        self._menus(window)
        self.retranslate()

    def _toolbar(self, window: QMainWindow) -> QToolBar:
        hub = self._hub
        bar = QToolBar(window)
        bar.setObjectName("toolbar_main")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for keys in (
            ("rescan", "sort", "validate"),
            ("backup", "patch"),
            ("profiles",),
            ("launch_game",),
        ):
            for key in keys:
                bar.addAction(hub[key])
            bar.addSeparator()
        self.slot_action = bar.addWidget(self.slot_combo)
        spacer = QWidget(bar)
        policy = QSizePolicy.Policy
        spacer.setSizePolicy(policy.Expanding, policy.Preferred)
        self.spacer_action = bar.addWidget(spacer)
        for key in ("undo", "redo", "find", "shortcuts"):
            bar.addAction(hub[key])
        window.addToolBar(bar)
        return bar

    def _add(self, name: str, title_key: str, window: QMainWindow, keys: list[str | None]) -> QMenu:
        menu = window.menuBar().addMenu("")
        menu.setObjectName(f"menu_{name}")
        menu.setProperty("title_key", title_key)
        for key in keys:
            if key is None:
                menu.addSeparator()
            else:
                menu.addAction(self._hub[key])
        self.menus[name] = menu
        return menu

    def _menus(self, window: QMainWindow) -> None:
        self._add(
            "file",
            "ui.menu.file",
            window,
            [
                "rescan", "backup", "patch", None, "profiles", "choose_save", "choose_mods",
                "edit_paths", "auto_detect", None, "open_save_folder", "open_local_mods",
                "launch_game", None, "quit",
            ],
        )  # fmt: skip
        self._add(
            "edit",
            "ui.menu.edit",
            window,
            [
                "undo", "redo", None, "find", None, "enable", "disable", None, "top", "up",
                "down", "bottom", None, "open_mod_folder", "open_mod_page", "forget_missing", None,
                "nickname", "assign_category",
            ],
        )  # fmt: skip
        self._add(
            "tools",
            "ui.menu.tools",
            window,
            [
                "sort", "auto_categorize", "validate", None, "edit_categories", None,
                "apply_order", "save_code", None, "patch_other", "patch_latest", None,
                "check_setup", "copy_debug", None, "settings", "plugin_approval",
            ],
        )  # fmt: skip
        view = self._add("view", "ui.menu.view", window, ["health"])
        for name, title_key, keys in (
            ("density", "ui.menu.density", [f"density_{slug}" for slug in DENSITY_SLUGS.values()]),
            ("language", "ui.menu.language", [f"lang_{c}" for c in LANGUAGES]),
            ("priority", "ui.menu.priority", ["prio_first", "prio_last", None, "prio_verified"]),
        ):
            sub = view.addMenu("")
            sub.setObjectName(f"menu_{name}")
            sub.setProperty("title_key", title_key)
            for key in keys:
                if key is None:
                    sub.addSeparator()
                else:
                    sub.addAction(self._hub[key])
            self.menus[name] = sub
        self._add("help", "ui.menu.help", window, ["shortcuts", "about"])

    def retranslate(self) -> None:
        tr = self._tr.tr
        for menu in self.menus.values():
            key = str(menu.property("title_key"))
            menu.setTitle(tr(key))
            menu.menuAction().setToolTip(tr(f"{key}.tip"))
        self.slot_combo.setToolTip(tr("ui.toolbar.slot.tip"))
        self.slot_action.setToolTip(tr("ui.toolbar.slot.tip"))
        self.toolbar.setWindowTitle(tr("ui.toolbar.title"))
        self.toolbar.toggleViewAction().setToolTip(tr("ui.toolbar.toggle.tip"))
        self.spacer_action.setToolTip(tr("ui.toolbar.spacer.tip"))
        self._tip_separators()

    def _tip_separators(self) -> None:
        """Separators are actions too; screen readers and the tooltip audit see every one."""
        tip = self._tr.tr("ui.window.separator.tip")
        holders = (self.toolbar, *self.menus.values())
        for action in (a for holder in holders for a in holder.actions() if a.isSeparator()):
            action.setToolTip(tip)
