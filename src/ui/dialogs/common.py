"""Small helpers shared by the dialogs."""

from collections.abc import Callable

from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from src.ui.theme.theme import set_role

type Tr = Callable[..., str]


def make_button(parent: QWidget, text: str, tip: str, *, role: str | None = None) -> QPushButton:
    """A push button whose tooltip always differs from its text."""
    button = QPushButton(text, parent)
    button.setToolTip(tip if tip != text else f"{tip}.")
    button.setAutoDefault(False)
    if role:
        set_role(button, role)
    return button


def button_row(*buttons: QAbstractButton, stretch_first: bool = True) -> QHBoxLayout:
    row = QHBoxLayout()
    if stretch_first:
        row.addStretch(1)
    for button in buttons:
        row.addWidget(button)
    return row


def make_button_box(dialog: QDialog, primary: QPushButton, cancel: QPushButton) -> QDialogButtonBox:
    """Accept/Reject buttons in the platform's order, wired to the dialog's accept/reject."""
    box = QDialogButtonBox(dialog)
    box.addButton(primary, QDialogButtonBox.ButtonRole.AcceptRole)
    box.addButton(cancel, QDialogButtonBox.ButtonRole.RejectRole)
    cancel.setDefault(True)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


def make_table(parent: QWidget, headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers), parent)
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    vertical = table.verticalHeader()
    if vertical is not None:
        vertical.setVisible(False)
    horizontal = table.horizontalHeader()
    if horizontal is not None:
        horizontal.setStretchLastSection(True)
    return table


def set_cell(
    table: QTableWidget, row: int, column: int, text: str, tip: str = ""
) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setToolTip(tip or text)
    table.setItem(row, column, item)
    return item


def finish(dialog: QDialog, title: str, width: int, height: int, tr: Tr) -> None:
    """Title and size, plus tooltips for Qt's own unlabeled buttons (table corners, tab arrows)."""
    dialog.setWindowTitle(title)
    dialog.resize(width, height)
    for button in dialog.findChildren(QAbstractButton):
        if not button.toolTip().strip():
            button.setToolTip(tr("ui.window.control.tip"))
