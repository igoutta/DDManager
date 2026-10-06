"""The Tools menu behind one object: apply order, auto categorize, save code, diagnostics."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication

from src.core.load_order import applied_entries
from src.core.loadorder_file import LegacyLoadoutExtras, LoadOrderDocument
from src.core.saves.applied_text import render_applied_text
from src.ui import controller_diagnostics as diagnostics
from src.ui.controller_apply import ApplyOrderFlow
from src.ui.controller_loadout import LoadoutFlow
from src.ui.controller_tools import DuplicateWatch, auto_categorize
from src.ui.presenters.tools_dto import DiagnosticsVM, SaveCodeVM

if TYPE_CHECKING:
    from src.ui.controller import MainController


class ToolsPresenter(QObject):
    """Entry points of the actions; windows get view models, flows do the work."""

    def __init__(self, controller: MainController) -> None:
        super().__init__(controller)
        self._c = controller
        self._apply = ApplyOrderFlow(controller)
        self._loadout = LoadoutFlow(controller)
        self._duplicates = DuplicateWatch(controller)
        controller.findingsChanged.connect(self._duplicates.on_findings)

    # ------------------------------------------------------------------ folders and categories

    def apply_order(self) -> None:
        """Rename the local mod folders to match the load order (preview, then rename)."""
        self._apply.start()

    def auto_categorize(self) -> None:
        """Assign a category to every mod without one; the load order never changes."""
        auto_categorize(self._c)

    # ------------------------------------------------------------------ text outputs

    def save_code(self) -> SaveCodeVM | None:
        """The applied block of the enabled mods as text; ``None`` (with a message) when there
        is nothing to show."""
        c = self._c
        if not c.order().active():
            c.post("ui.notice.no_enabled", "warning")
            return None
        try:
            entries = applied_entries(c.order(), c.identity_map())
        except ValueError as exc:
            c.prompter_error("ui.error.identity_missing_code", str(exc))
            return None
        return SaveCodeVM(render_applied_text(entries), len(entries))

    def diagnostics(self, on_ready: Callable[[DiagnosticsVM], None]) -> None:
        """Gather the setup report in the background; ``on_ready`` gets it on the GUI thread."""
        diagnostics.collect(self._c, on_ready)

    def copy_debug_info(self) -> None:
        """Copy the setup report to the clipboard (the same text the dialog shows)."""
        c = self._c

        def copy(vm: DiagnosticsVM) -> None:
            QGuiApplication.clipboard().setText(vm.text)
            c.post("debug_info_copied_body")

        diagnostics.collect(c, copy)

    # ------------------------------------------------------------------ legacy import

    def import_legacy(self, doc: LoadOrderDocument, extras: LegacyLoadoutExtras) -> None:
        """Apply a legacy ``dd_mod_loadout.json``: the order after its preview, then the extras."""
        self._loadout.import_legacy(doc, extras)
