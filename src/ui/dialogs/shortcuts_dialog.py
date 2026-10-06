"""The F1 cheat sheet, generated from the window's actions."""

from collections.abc import Sequence

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from src.ui.dialogs.common import button_row, finish, make_button, make_table, set_cell
from src.ui.i18n import Translator


def shortcut_rows(actions: Sequence[QAction]) -> list[tuple[str, str, str]]:
    """``(name, keys, description)`` of every action that has a shortcut, in action order."""
    rows: list[tuple[str, str, str]] = []
    for action in actions:
        keys = ", ".join(
            seq.toString(QKeySequence.SequenceFormat.NativeText) for seq in action.shortcuts()
        )
        if keys:
            rows.append((action.text().replace("&", ""), keys, action.statusTip()))
    return rows


class ShortcutsDialog(QDialog):
    def __init__(
        self, actions: Sequence[QAction], translator: Translator, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        tr = translator.tr
        self.setObjectName("dialog_shortcuts")
        layout = QVBoxLayout(self)
        rows = shortcut_rows(actions)
        self.table = make_table(
            self,
            [
                tr("ui.shortcuts.col.action"),
                tr("ui.shortcuts.col.keys"),
                tr("ui.shortcuts.col.what"),
            ],
        )
        self.table.setRowCount(len(rows))
        for row, (name, keys, what) in enumerate(rows):
            set_cell(self.table, row, 0, name)
            set_cell(self.table, row, 1, keys)
            set_cell(self.table, row, 2, what)
        self.table.resizeColumnsToContents()
        self.close_button = make_button(
            self, tr("ui.dialog.close"), tr("ui.dialog.close.tip"), role="primary"
        )
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(self.table, 1)
        layout.addLayout(button_row(self.close_button))
        finish(self, tr("ui.shortcuts.title"), 640, 560, tr)
