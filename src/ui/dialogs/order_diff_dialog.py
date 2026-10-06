"""Preview of an order change (Auto-Sort, profile apply, import from a save)."""

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget

from src.ui.dialogs.common import finish, make_button, make_button_box, make_table, set_cell
from src.ui.i18n import Translator
from src.ui.theme.theme import set_role
from src.ui.viewmodels import OrderDiffVM

_HIGHLIGHT_ALPHA = 70


class OrderDiffDialog(QDialog):
    """Rows of the proposed order with old and new rank; moved rows are highlighted."""

    def __init__(
        self, vm: OrderDiffVM, title: str, translator: Translator, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        tr = translator.tr
        self.setObjectName("dialog_order_diff")
        layout = QVBoxLayout(self)
        self.summary = QLabel(
            tr(
                "ui.diff.summary",
                moved=vm.moved_count,
                total=vm.total,
                added=vm.added,
                removed=vm.removed,
            )
        )
        set_role(self.summary, "heading")
        self.table = make_table(
            self,
            [
                tr("ui.diff.col.title"),
                tr("ui.diff.col.old"),
                tr("ui.diff.col.new"),
                tr("ui.diff.col.delta"),
            ],
        )
        self._fill(vm, translator)
        self.apply_button = make_button(
            self, tr("ui.diff.apply"), tr("ui.diff.apply.tip"), role="primary"
        )
        self.cancel_button = make_button(self, tr("ui.dialog.cancel"), tr("ui.dialog.cancel.tip"))
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)
        layout.addWidget(make_button_box(self, self.apply_button, self.cancel_button))
        finish(self, title, 640, 520, tr)

    def _fill(self, vm: OrderDiffVM, translator: Translator) -> None:
        highlight = QColor(self.palette().color(self.palette().ColorRole.Highlight))
        highlight.setAlpha(_HIGHLIGHT_ALPHA)
        self.table.setRowCount(len(vm.rows))
        for row, entry in enumerate(vm.rows):
            old = "" if entry.old_rank is None else str(entry.old_rank)
            new = "" if entry.new_rank is None else str(entry.new_rank)
            delta = self._delta(entry.old_rank, entry.new_rank, translator)
            cells = [
                set_cell(self.table, row, 0, entry.title, f"{entry.title}\n{entry.mod_id}"),
                set_cell(self.table, row, 1, old),
                set_cell(self.table, row, 2, new),
                set_cell(self.table, row, 3, delta),
            ]
            if entry.old_rank != entry.new_rank:
                for cell in cells:
                    cell.setBackground(QBrush(highlight))

    @staticmethod
    def _delta(old: int | None, new: int | None, translator: Translator) -> str:
        if old is None:
            return translator.tr("ui.diff.added")
        if new is None:
            return translator.tr("ui.diff.removed")
        return "" if old == new else f"{old - new:+d}"
