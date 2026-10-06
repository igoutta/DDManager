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


def set_button_text(button: QAbstractButton, text: str, tip: str) -> None:
    """(Re)label a button: its tooltip always differs from its text."""
    button.setText(text)
    button.setToolTip(tip if tip != text else f"{tip}.")


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


CHROME_TIP_KEY = "chrome_tip_key"
CHROME_TIP_TEXT = "chrome_tip_text"
_GENERIC_TIP = "ui.window.control.tip"


def tip_chrome(
    root: QWidget, tr: Tr, key_for: Callable[[QAbstractButton], str] | None = None
) -> None:
    """Tooltips for Qt's own unlabeled buttons (table corners, tab arrows, dock buttons).

    A button that has no tooltip gets the catalog text of ``key_for(button)`` (default: the
    generic control tip) and remembers the key; calling again after a language change re-tips
    every remembered button whose tooltip is still the text set here, so a real tooltip its
    owner set later is never overwritten.
    """
    for button in root.findChildren(QAbstractButton):
        current = button.toolTip()
        key = button.property(CHROME_TIP_KEY)
        ours = bool(key) and current == button.property(CHROME_TIP_TEXT)
        if not ours and current.strip():
            continue
        if not key:
            key = key_for(button) if key_for is not None else _GENERIC_TIP
            button.setProperty(CHROME_TIP_KEY, key)
        text = tr(str(key))
        button.setProperty(CHROME_TIP_TEXT, text)
        button.setToolTip(text)


def finish(dialog: QDialog, title: str, width: int, height: int, tr: Tr) -> None:
    """Title and size, plus tooltips for Qt's own unlabeled buttons (table corners, tab arrows)."""
    dialog.setWindowTitle(title)
    dialog.resize(width, height)
    tip_chrome(dialog, tr)
