"""The management actions: categories, nicknames, file paths, settings and plugin approval.

``manage_specs`` builds the :class:`ActionSpec` s for the action hub; ``bind_manage_actions`` is
called once the actions exist: it hangs the "Assign Category" submenu on its action and keeps the
selection-dependent actions enabled correctly.
"""

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDialog, QMenu

from src.core.ids import ModId
from src.ui.dialogs.categories_dialog import CategoriesDialog, swatch
from src.ui.dialogs.nickname_dialog import NicknameDialog
from src.ui.dialogs.paths_dialog import PathsDialog
from src.ui.dialogs.plugin_approval_dialog import PluginApprovalDialog
from src.ui.dialogs.settings_dialog import SettingsDialog
from src.ui.theme.tokens import TIER_TOKENS
from src.ui.widgets.actions import ActionSpec

if TYPE_CHECKING:
    from src.ui.widgets.main_window import MainWindow

_UNASSIGNED_COLOR = TIER_TOKENS["unassigned"].color


class ManageDialogs(QObject):
    """Opens the management dialogs and owns the "Assign Category" submenu."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self._w = window
        self._actions: Mapping[str, QAction] = {}
        self.assign_menu = QMenu(window)
        self.assign_menu.setObjectName("menu_assign_category")
        self.assign_menu.aboutToShow.connect(self._fill_menu)
        window.controller.detailsChanged.connect(self.refresh)
        window.translator.languageChanged.connect(self.retranslate)
        self.retranslate()

    # ------------------------------------------------------------------ binding

    def bind(self, actions: Mapping[str, QAction]) -> None:
        self._actions = actions
        actions["assign_category"].setMenu(self.assign_menu)
        self.refresh()

    def retranslate(self, *_args: object) -> None:
        """The submenu's own action (listed by accessibility tools) needs a title and a tooltip."""
        tr = self._w.translator.tr
        self.assign_menu.setTitle(tr("ui.action.assign_category"))
        self.assign_menu.menuAction().setToolTip(tr("ui.action.assign_category.tip"))

    def refresh(self, *_args: object) -> None:
        """Assign needs a selection; a nickname needs exactly one installed mod."""
        actions = self._actions
        if not actions:
            return
        c = self._w.controller
        ids = c.selection()
        actions["assign_category"].setEnabled(bool(ids))
        actions["nickname"].setEnabled(len(ids) == 1 and ids[0] in c.mods())

    def _fill_menu(self) -> None:
        """One entry per category (colored swatch), then Unassigned; built each time it opens."""
        w = self._w
        c = w.controller
        tr = w.translator.tr
        menu = self.assign_menu
        menu.clear()
        ids = list(c.selection())
        for choice in c.labels.category_choices():
            action = menu.addAction(swatch(choice.color), choice.label)
            action.setToolTip(tr("ui.categories.assign.tip", category=choice.label))
            action.triggered.connect(self._assigner(ids, choice.name))
        separator = menu.addSeparator()
        separator.setToolTip(tr("ui.window.separator.tip"))
        none = menu.addAction(swatch(_UNASSIGNED_COLOR), tr("category_unassigned"))
        none.setToolTip(tr("ui.categories.unassign.tip"))
        none.triggered.connect(self._assigner(ids, None))

    def _assigner(self, ids: list[ModId], name: str | None) -> Callable[[], None]:
        controller = self._w.controller
        return lambda: controller.set_category(ids, name)

    # ------------------------------------------------------------------ dialogs

    def _run(self, dialog: QDialog) -> bool:
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        dialog.deleteLater()
        return accepted

    def open_categories(self) -> None:
        w = self._w
        self._run(CategoriesDialog(w.controller.categories, w.translator, w.icons, w))

    def open_paths(self) -> None:
        w = self._w
        self._run(PathsDialog(w.controller.paths, w.translator, w.icons, w))

    def open_settings(self) -> None:
        w = self._w
        self._run(SettingsDialog(w.controller.settings, w.translator, w.icons, w))

    def open_plugin_approval(self) -> None:
        w = self._w
        self._run(PluginApprovalDialog(w.controller.settings.trust, w.translator, w.icons, w))

    def offer_plugin_approval(self) -> None:
        """Start-up hook: ask only when user plugins are on and some file is new or changed."""
        if self._w.controller.settings.trust.needs_approval():
            self.open_plugin_approval()

    def open_nickname(self) -> None:
        w = self._w
        c = w.controller
        ids = c.selection()
        vm = c.labels.nickname_vm(ids[0]) if len(ids) == 1 else None
        if vm is None:
            c.post("select_one_mod_to_nickname", "warning")
            return
        dialog = NicknameDialog(vm, w.translator, w.icons, w)
        if self._run(dialog):
            c.set_nickname(vm.mod_id, dialog.text())


def _noop() -> None:
    """The "Assign Category" action only opens its submenu."""


def manage_specs(window: MainWindow) -> list[ActionSpec]:
    manager = ManageDialogs(window)
    c = window.controller
    return [
        ActionSpec("edit_paths", "folder", manager.open_paths),
        ActionSpec("auto_detect", "find", c.paths.auto_detect),
        ActionSpec("edit_categories", "sort", manager.open_categories),
        ActionSpec("settings", "check", manager.open_settings, ("Ctrl+,",)),
        ActionSpec("plugin_approval", "warning", manager.open_plugin_approval),
        ActionSpec("nickname", "info", manager.open_nickname, ("F2",)),
        ActionSpec("assign_category", "sort", _noop),
    ]


def bind_manage_actions(window: MainWindow, actions: Mapping[str, QAction]) -> None:
    manager = window.findChild(ManageDialogs)
    if manager is not None:
        manager.bind(actions)


def offer_plugin_approval(window: MainWindow) -> None:
    """Start-up hook of the composition root (see :meth:`ManageDialogs.offer_plugin_approval`)."""
    manager = window.findChild(ManageDialogs)
    if manager is not None:
        manager.offer_plugin_approval()
