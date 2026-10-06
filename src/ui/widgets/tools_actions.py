"""The Tools actions (apply order, auto categorize, save code, check setup, debug info)."""

from typing import TYPE_CHECKING

from src.ui.dialogs.diagnostics_dialog import DiagnosticsDialog
from src.ui.dialogs.save_code_dialog import SaveCodeDialog
from src.ui.presenters.tools_dto import DiagnosticsVM
from src.ui.widgets.actions import ActionSpec

if TYPE_CHECKING:
    from src.ui.widgets.main_window import MainWindow


class ToolsDialogs:
    """Opens the text dialogs of the Tools menu; the presenter supplies their view models."""

    def __init__(self, window: MainWindow) -> None:
        self._w = window

    def open_save_code(self) -> None:
        w = self._w
        vm = w.controller.tools.save_code()
        if vm is not None:
            SaveCodeDialog(vm, w.translator, w.icons, w).exec()

    def open_diagnostics(self) -> None:
        self._w.controller.tools.diagnostics(self._show_diagnostics)

    def _show_diagnostics(self, vm: DiagnosticsVM) -> None:
        w = self._w
        DiagnosticsDialog(vm, w.translator, w.icons, w).exec()


def tools_specs(window: MainWindow) -> list[ActionSpec]:
    tools = window.controller.tools
    dialogs = ToolsDialogs(window)
    return [
        ActionSpec("auto_categorize", "sort", tools.auto_categorize),
        ActionSpec("apply_order", "folder", tools.apply_order, danger=True),
        ActionSpec("save_code", "patch", dialogs.open_save_code),
        ActionSpec("check_setup", "check", dialogs.open_diagnostics),
        ActionSpec("copy_debug", "info", tools.copy_debug_info),
    ]
