"""The category editor: reorder, add, rename, recolor and remove categories, then Save or Cancel.

Every edit goes to the presenter's draft; nothing is written until Save (``dd2.py:5307-5661``).
"""

from typing import TYPE_CHECKING, Final, override

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.dialogs.common import finish, make_button, make_button_box, set_button_text
from src.ui.dialogs.live_dialog import LiveDialog
from src.ui.i18n import Translator
from src.ui.theme.theme import set_role
from src.ui.widgets.actions import IconSet

if TYPE_CHECKING:
    from src.ui.presenters.categories import CategoriesPresenter, Problem

_NAME_ROLE: Final = Qt.ItemDataRole.UserRole
_SWATCH_PX: Final = 14
_LIGHT_LUMA: Final = 140
_ACTIONS: Final = ("up", "down", "add", "rename", "set_color", "reset_color", "remove")


def swatch(color: str) -> QIcon:
    pixmap = QPixmap(_SWATCH_PX, _SWATCH_PX)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


class CategoryList(QListWidget):
    """One category per row; dragging a row reorders the list (single selection)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)

    def names(self) -> list[str]:
        items = (self.item(row) for row in range(self.count()))
        return [str(item.data(_NAME_ROLE)) for item in items if item is not None]


class CategoriesDialog(LiveDialog):
    def __init__(
        self,
        presenter: CategoriesPresenter,
        translator: Translator,
        icons: IconSet,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(translator, parent)
        self._p = presenter
        self._icons = icons
        self._syncing = False
        self.setObjectName("dialog_categories")
        presenter.begin()
        self.heading = QLabel(self)
        set_role(self.heading, "heading")
        self.list = CategoryList(self)
        self.preview = QLabel(self)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(40)
        self.hint = QLabel(self)
        self.hint.setWordWrap(True)
        set_role(self.hint, "muted")
        self.buttons: dict[str, QPushButton] = {
            name: make_button(self, name, name, role="danger" if name == "remove" else None)
            for name in _ACTIONS
        }
        self.save_button = make_button(self, "save", "save.tip", role="primary")
        self.cancel_button = make_button(self, "cancel", "cancel.tip")
        self._build_layout()
        self._wire()
        self.refresh()
        self.retranslate_ui()
        finish(self, self.windowTitle(), 640, 480, translator.tr)

    # ------------------------------------------------------------------ construction

    def _build_layout(self) -> None:
        side = QVBoxLayout()
        side.addWidget(self.preview)
        for button in self.buttons.values():
            side.addWidget(button)
        side.addStretch(1)
        body = QHBoxLayout()
        body.addWidget(self.list, 1)
        body.addLayout(side)
        layout = QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addLayout(body, 1)
        layout.addWidget(self.hint)
        layout.addWidget(make_button_box(self, self.save_button, self.cancel_button))

    def _wire(self) -> None:
        self._p.changed.connect(self.refresh)
        self.list.currentRowChanged.connect(self._update_preview)
        self.list.model().rowsMoved.connect(self._on_moved)
        handlers = {
            "up": lambda: self._move(-1),
            "down": lambda: self._move(1),
            "add": self._add,
            "rename": self._rename,
            "set_color": self._set_color,
            "reset_color": self._reset_color,
            "remove": self._remove,
        }
        for name, handler in handlers.items():
            self.buttons[name].clicked.connect(handler)

    # ------------------------------------------------------------------ list

    def refresh(self) -> None:
        """Rebuild the list from the draft, keeping the selected row where it makes sense."""
        if self._syncing:
            return
        row = self.list.currentRow()
        self.list.blockSignals(True)  # noqa: FBT003
        self.list.clear()
        for vm in self._p.rows():
            item = QListWidgetItem(swatch(vm.color), vm.label)
            item.setData(_NAME_ROLE, vm.name)
            item.setForeground(QColor(vm.color))
            item.setToolTip(vm.label)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            self.list.addItem(item)
        self.list.setCurrentRow(max(0, min(row, self.list.count() - 1)))
        self.list.blockSignals(False)  # noqa: FBT003
        self._update_preview()

    def current_row(self) -> int:
        return self.list.currentRow()

    def select(self, row: int) -> None:
        self.list.setCurrentRow(row)

    def _on_moved(self, *_args: object) -> None:
        """The list moved a row itself (drag and drop): adopt its order in the draft."""
        self._syncing = True
        try:
            self._p.reorder(self.list.names())
        finally:
            self._syncing = False
        self._update_preview()

    def _update_preview(self, *_args: object) -> None:
        tr = self._translator.tr
        row = self.list.currentRow()
        rows = self._p.rows()
        if not 0 <= row < len(rows):
            self.preview.setText(tr("category_editor_no_category"))
            self._paint_preview(self._icons.color("panel_deep"))
            return
        color = rows[row].color
        self.preview.setText(tr("category_editor_color", color=color))
        self._paint_preview(color)

    def _paint_preview(self, color: str) -> None:
        """Fill the swatch with ``color`` and pick the readable one of two palette text colors."""
        fill = QColor(color)
        luma = (299 * fill.red() + 587 * fill.green() + 114 * fill.blue()) // 1000
        text = self._icons.color("ink" if luma >= _LIGHT_LUMA else "text_bright")
        border = self._icons.color("border")
        self.preview.setStyleSheet(
            f"background: {fill.name()}; color: {text}; border: 1px solid {border};"
        )

    # ------------------------------------------------------------------ actions

    def _show(self, problem: Problem) -> None:
        tr = self._translator.tr
        text = tr(problem.key, **dict(problem.params))
        if problem.level == "info":
            QMessageBox.information(self, tr("ui.categories.builtin_title"), text)
        else:
            QMessageBox.warning(self, tr("warning"), text)

    def _move(self, delta: int) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.select(self._p.move(row, delta))

    def _ask_name(self, title_key: str, initial: str = "") -> str | None:
        tr = self._translator.tr
        text, ok = QInputDialog.getText(
            self, tr(title_key), tr("ui.categories.name_prompt"), QLineEdit.EchoMode.Normal, initial
        )
        return text if ok else None

    def _ask_color(self, initial: str) -> str | None:
        chosen = QColorDialog.getColor(
            QColor(initial), self, self._translator.tr("ui.categories.color_title")
        )
        return chosen.name().upper() if chosen.isValid() else None

    def _add(self) -> None:
        raw = self._ask_name("ui.categories.add_title")
        if raw is None:
            return
        _name, problem = self._p.check_name(raw)
        if problem is not None:
            self._show(problem)
            return
        color = self._ask_color(self._p.default_color())
        problem = self._p.add(raw, color)
        if problem is None:
            self.select(self.list.count() - 1)
        else:
            self._show(problem)

    def _rename(self) -> None:
        row = self.list.currentRow()
        names = self._p.names()
        if not 0 <= row < len(names):
            return
        problem = self._p.builtin_problem(row, "rename")
        if problem is None:
            raw = self._ask_name("ui.categories.rename_title", names[row])
            problem = self._p.rename(row, raw) if raw is not None else None
        if problem is not None:
            self._show(problem)

    def _set_color(self) -> None:
        row = self.list.currentRow()
        names = self._p.names()
        if not 0 <= row < len(names):
            return
        color = self._ask_color(self._p.color_of(names[row]))
        if color is not None:
            self._p.set_color(row, color)

    def _reset_color(self) -> None:
        self._p.reset_color(self.list.currentRow())

    def _remove(self) -> None:
        row = self.list.currentRow()
        names = self._p.names()
        if not 0 <= row < len(names):
            return
        problem = self._p.builtin_problem(row, "remove")
        if problem is None:
            tr = self._translator.tr
            answer = QMessageBox.question(
                self,
                tr("ui.categories.remove_title"),
                tr("ui.categories.remove_confirm", name=names[row]),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            problem = self._p.remove(row)
        if problem is not None:
            self._show(problem)

    # ------------------------------------------------------------------ dialog

    @override
    def accept(self) -> None:
        self._p.commit()
        super().accept()

    @override
    def retranslate_ui(self) -> None:
        tr = self._translator.tr
        self.setWindowTitle(tr("edit_categories"))
        self.heading.setText(tr("ui.categories.heading"))
        self.hint.setText(tr("category_editor_hint"))
        self.list.setToolTip(tr("ui.categories.list.tip"))
        self.preview.setToolTip(tr("ui.categories.preview.tip"))
        for name, button in self.buttons.items():
            set_button_text(button, tr(f"category_editor_{name}"), tr(f"ui.categories.{name}.tip"))
        set_button_text(self.save_button, tr("save"), tr("ui.dialog.save.tip"))
        set_button_text(self.cancel_button, tr("cancel"), tr("ui.dialog.cancel.tip"))
        self.refresh()
