"""The main window: toolbar, menus, the three panes, the health dock and the status bar."""

from pathlib import Path
from typing import override

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import QAbstractButton, QMainWindow, QMessageBox, QSplitter

from src.__about__ import __version__
from src.core.ids import ModId
from src.core.load_order import MoveOp, PriorityDirection
from src.ui.controller import MainController
from src.ui.dialogs.common import tip_chrome
from src.ui.dialogs.profile_manager_dialog import ProfileManagerDialog
from src.ui.dialogs.shortcuts_dialog import ShortcutsDialog
from src.ui.i18n import Translator
from src.ui.theme.tokens import DENSITY, ThemeTokens
from src.ui.viewmodels import NoticeVM, StatusVM
from src.ui.widgets.actions import IconSet, application_icon
from src.ui.widgets.available_pane import AvailablePane
from src.ui.widgets.details_pane import DetailsPane
from src.ui.widgets.health_dock import HealthDock
from src.ui.widgets.load_order_pane import LoadOrderPane
from src.ui.widgets.status_bar import AppStatusBar
from src.ui.widgets.window_actions import DENSITY_SLUGS, LANGUAGES, ActionHub
from src.ui.widgets.window_menus import WindowChrome
from src.ui.widgets.window_state import apply_default_split, restore_ui_state, save_ui_state

_STRETCH = (3, 5, 3)
# Qt's own chrome buttons (dock close/float, toolbar overflow, ...) and their generic tooltips.
_CHROME_KEYS = {
    "qt_toolbar_ext_button": "ui.window.more.tip",
    "qt_menubar_ext_button": "ui.window.more.tip",
    "qt_tableview_cornerbutton": "ui.window.corner.tip",
    "qt_dockwidget_floatbutton": "ui.window.float_dock.tip",
    "qt_dockwidget_closebutton": "ui.window.close_dock.tip",
}


class MainWindow(QMainWindow):
    def __init__(
        self,
        controller: MainController,
        translator: Translator,
        tokens: ThemeTokens,
        icons: IconSet,
        ui_ini: Path | None = None,
    ) -> None:
        super().__init__()
        self.controller = controller
        self._live = True
        self.translator = translator
        self.tokens = tokens
        self.icons = icons
        self._ui_ini = ui_ini if ui_ini is not None else controller.ui_ini()
        self.setObjectName("main_window")
        self.hub = ActionHub(self, translator, icons)
        self.chrome = WindowChrome(self, self.hub, translator)
        self._build_panes()
        self.dock = HealthDock(controller, translator, icons, self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock)
        self.dock.hide()
        self.status_bar = AppStatusBar(translator, tokens, icons, self)
        self.setStatusBar(self.status_bar)
        self._bind_actions()
        self._connect()
        self.apply_density(self._density())
        self.retranslate_ui()
        self.resize(1360, 820)
        self.restore_ui_state()
        self._on_status(controller.status())
        self.refresh_slots()
        self.refresh_actions()

    # ------------------------------------------------------------------ construction

    def _build_panes(self) -> None:
        c, tr, tok = self.controller, self.translator, self.tokens
        self.available = AvailablePane(c, tr, tok, self)
        self.load_order = LoadOrderPane(c, tr, tok, self)
        self.details = DetailsPane(c, tr, self.icons, self)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setObjectName("splitter_main")
        for index, pane in enumerate((self.available, self.load_order, self.details)):
            self.splitter.addWidget(pane)
            self.splitter.setStretchFactor(index, _STRETCH[index])
        self.setCentralWidget(self.splitter)

    def _bind_actions(self) -> None:
        hub = self.hub
        self.available.addAction(hub["enable"])
        self.available.view.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.available.view.addActions(
            [
                hub["enable"],
                hub["open_mod_folder"],
                hub["open_mod_page"],
                hub["forget_missing"],
                hub["nickname"],
                hub["assign_category"],
            ]
        )
        self.load_order.attach_actions(
            [hub[k] for k in ("enable", "disable", "top", "up", "down", "bottom")],
            [
                hub["disable"], hub["top"], hub["up"], hub["down"], hub["bottom"], None,
                hub["open_mod_folder"], hub["open_mod_page"], hub["forget_missing"], None,
                hub["nickname"], hub["assign_category"],
            ],
            shortcut_actions=[hub[k] for k in ("disable", "top", "up", "down", "bottom")],
        )  # fmt: skip

    def _connect(self) -> None:
        c = self.controller
        c.destroyed.connect(self._on_controller_gone)
        c.statusChanged.connect(self._on_status)
        c.detailsChanged.connect(self.details.show_details)
        c.notice.connect(self._on_notice)
        c.slotsChanged.connect(self.refresh_slots)
        c.densityChanged.connect(self.apply_density)
        c.selectModsRequested.connect(self._select_requested)
        c.busyChanged.connect(self._on_busy)
        c.undo_stack.indexChanged.connect(self._on_stack_changed)
        c.findingsChanged.connect(self._on_stack_changed)
        for pane in (self.available, self.load_order):
            pane.selectionChangedIds.connect(self._on_selection)
        self.load_order.actionsStale.connect(self.refresh_actions)
        self.load_order.unverifiedClicked.connect(self._explain_unverified)
        self.status_bar.countsClicked.connect(self.show_health)
        self.status_bar.saveFolderRequested.connect(c.open_save_folder)
        self.status_bar.reloadRequested.connect(c.reload_state)
        self.status_bar.keepMineRequested.connect(c.keep_mine)
        self.chrome.slot_combo.activated.connect(self._on_slot_chosen)
        self.dock.visibilityChanged.connect(self.hub["health"].setChecked)
        self.translator.languageChanged.connect(self._on_language)

    # ------------------------------------------------------------------ slots from actions

    def quit_app(self) -> None:
        self.close()

    def focus_search(self) -> None:
        self.available.focus_search()

    def enable_selection(self) -> None:
        self.available.enable_selection()

    def disable_selection(self) -> None:
        self.load_order.disable_selection()

    def move_selection(self, op: MoveOp) -> None:
        self.load_order.move_selection(op)

    def run_validate(self) -> None:
        self.controller.validate()
        self.show_health()

    def show_health(self) -> None:
        self.dock.show()
        self.dock.raise_()

    def toggle_health(self) -> None:
        self.dock.setVisible(self.hub["health"].isChecked())

    def toggle_verified(self) -> None:
        presenter = self.controller.settings
        presenter.set_priority(
            presenter.priority().direction, verified=self.hub["prio_verified"].isChecked()
        )

    def _selected(self) -> list[ModId]:
        return list(self.controller.selection())

    def open_mod_folder(self) -> None:
        ids = self._selected()
        if ids:
            self.controller.open_folder(ids[0])

    def open_mod_page(self) -> None:
        ids = self._selected()
        if ids:
            self.controller.open_workshop_page(ids[0])

    def forget_missing(self) -> None:
        self.controller.forget_missing(self._selected())

    def open_profile_manager(self) -> None:
        dialog = ProfileManagerDialog(self.controller.profiles, self.translator, self.icons, self)
        dialog.exec()

    def open_shortcuts(self) -> None:
        ShortcutsDialog(list(self.hub.actions.values()), self.translator, self).exec()

    def open_about(self) -> None:
        tr = self.translator.tr
        QMessageBox.about(self, tr("ui.about.title"), tr("ui.about.body", version=__version__))

    # ------------------------------------------------------------------ reactions

    def _on_controller_gone(self, *_args: object) -> None:
        self._live = False

    def _on_stack_changed(self, *_args: object) -> None:
        self.refresh_actions()

    def _on_language(self, *_args: object) -> None:
        self.retranslate_ui()
        self._sync_checks()

    def _on_selection(self, ids: list[ModId]) -> None:
        self.controller.select(ids)
        self.refresh_actions()

    def _select_requested(self, ids: list[ModId]) -> None:
        self.available.select(ids)
        self.load_order.select(ids)

    def _on_status(self, vm: StatusVM) -> None:
        self.status_bar.set_status(vm)
        self.load_order.update_status(vm)
        self.refresh_actions()

    def _on_notice(self, notice: NoticeVM) -> None:
        self.status_bar.notify(self.translator.tr(notice.key, **dict(notice.params)))

    def _on_busy(self, busy: bool) -> None:
        for view in (self.available.view, self.load_order.view):
            view.setDragEnabled(not busy)

    def _explain_unverified(self) -> None:
        if self.controller.prompter is not None:
            self.controller.prompter.info("ui.dir.unverified_help")

    def _density(self) -> str:
        mode = self.controller.density()
        return mode if mode in DENSITY else "Comfortable"

    def apply_density(self, mode: str) -> None:
        self.available.set_density(mode)
        self.load_order.set_density(mode)
        self.hub[f"density_{DENSITY_SLUGS.get(mode, 'comfortable')}"].setChecked(True)

    def refresh_slots(self) -> None:
        combo = self.chrome.slot_combo
        combo.blockSignals(True)  # noqa: FBT003
        combo.clear()
        current = self.controller.save_path()
        for label, path in self.controller.profiles.slot_choices():
            combo.addItem(label, str(path))
            if path == current:
                combo.setCurrentIndex(combo.count() - 1)
        combo.blockSignals(False)  # noqa: FBT003

    def _on_slot_chosen(self, index: int) -> None:
        data = self.chrome.slot_combo.itemData(index)
        if data:
            self.controller.profiles.use_slot(Path(str(data)))

    # ------------------------------------------------------------------ action state

    def refresh_actions(self) -> None:
        if not self._live:
            return
        c, hub = self.controller, self.hub
        flags = self.load_order.noop_flags()
        hub["disable"].setEnabled(not flags["none"])
        for key in ("top", "up", "down", "bottom"):
            hub[key].setEnabled(not flags[key])
        rows = c.rows()
        hub["enable"].setEnabled(
            any(m in rows and not rows[m].enabled for m in self.available.selected_ids())
        )
        hub["undo"].setEnabled(c.undo_stack.canUndo())
        hub["redo"].setEnabled(c.undo_stack.canRedo())
        has_save = c.save_path() is not None
        for key in ("backup", "patch", "open_save_folder"):
            hub[key].setEnabled(has_save)
        selected = self._selected()
        hub["open_mod_folder"].setEnabled(len(selected) == 1)
        hub["open_mod_page"].setEnabled(len(selected) == 1 and bool(c.page_url(selected[0])))
        hub["forget_missing"].setEnabled(any(rows[m].missing for m in selected if m in rows))
        self._sync_checks()

    def _sync_checks(self) -> None:
        priority = self.controller.priority()
        first = priority.direction is PriorityDirection.FIRST_WINS
        self.hub["prio_first" if first else "prio_last"].setChecked(True)
        self.hub["prio_verified"].setChecked(priority.verified)
        language = self.translator.language()
        if language in LANGUAGES:
            self.hub[f"lang_{language}"].setChecked(True)

    # ------------------------------------------------------------------ language and state

    def retranslate_ui(self) -> None:
        tr = self.translator.tr
        self.setWindowTitle(tr("app_title"))
        if self.windowIcon().isNull():
            self.setWindowIcon(application_icon())
        self.hub.retranslate()
        self.chrome.retranslate()
        self.available.retranslate_ui()
        self.load_order.retranslate_ui()
        self.details.retranslate_ui()
        self.dock.retranslate_ui()
        self.status_bar.retranslate_ui()
        self.refresh_slots()
        tip_chrome(self, tr, self._chrome_key)

    def _chrome_key(self, button: QAbstractButton) -> str:
        """The generic tooltip key of one of Qt's own unlabeled buttons."""
        if button.parent() is self.available.search:
            return "ui.window.clear.tip"
        return _CHROME_KEYS.get(button.objectName(), "ui.window.control.tip")

    def save_ui_state(self) -> None:
        save_ui_state(self, self.splitter, self._ui_ini)

    def restore_ui_state(self) -> None:
        """Restore ui.ini; without a saved splitter the first show applies the default split."""
        self._default_split = not restore_ui_state(self, self.splitter, self._ui_ini)

    @override
    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._default_split:
            self._default_split = False
            apply_default_split(self.splitter)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if not self.controller.can_close():
            event.ignore()
            return
        self.save_ui_state()
        super().closeEvent(event)
