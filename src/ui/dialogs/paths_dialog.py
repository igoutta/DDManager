"""The file-paths editor: the five legacy path settings with Browse, Auto and Clear each.

``dd2.py:5836-5885``: a blank field keeps using auto-detection for that path.
"""

from typing import TYPE_CHECKING, override

from PySide6.QtWidgets import QGridLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from src.ui.dialogs.common import finish, make_button, make_button_box, set_button_text
from src.ui.dialogs.live_dialog import LiveDialog
from src.ui.i18n import Translator
from src.ui.theme.theme import set_role
from src.ui.widgets.actions import IconSet

if TYPE_CHECKING:
    from src.ui.presenters.paths import PathEntryVM, PathsPresenter

_ROW_BUTTONS = ("browse", "auto", "clear")


class PathRow:
    """The widgets of one path setting."""

    def __init__(self, entry: PathEntryVM, parent: QWidget) -> None:
        self.entry = entry
        self.label = QLabel(parent)
        self.edit = QLineEdit(entry.value, parent)
        self.edit.setObjectName(f"edit_{entry.key}")
        self.buttons: dict[str, QPushButton] = {
            name: make_button(parent, name, name) for name in _ROW_BUTTONS
        }
        for name, button in self.buttons.items():
            button.setObjectName(f"{name}_{entry.key}")


class PathsDialog(LiveDialog):
    def __init__(
        self,
        presenter: PathsPresenter,
        translator: Translator,
        icons: IconSet,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(translator, parent)
        self._p = presenter
        self._icons = icons
        self.setObjectName("dialog_paths")
        self.heading = QLabel(self)
        set_role(self.heading, "heading")
        self.hint = QLabel(self)
        set_role(self.hint, "muted")
        self.rows = {entry.key: PathRow(entry, self) for entry in presenter.entries()}
        self.save_button = make_button(self, "save", "save.tip", role="primary")
        self.cancel_button = make_button(self, "cancel", "cancel.tip")
        self._build_layout()
        for key, row in self.rows.items():
            row.buttons["browse"].clicked.connect(lambda _=False, k=key: self._browse(k))
            row.buttons["auto"].clicked.connect(lambda _=False, k=key: self._auto(k))
            row.buttons["clear"].clicked.connect(row.edit.clear)
        self.retranslate_ui()
        finish(self, self.windowTitle(), 1020, 380, translator.tr)

    def _build_layout(self) -> None:
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        for index, row in enumerate(self.rows.values()):
            grid.addWidget(row.label, index, 0)
            grid.addWidget(row.edit, index, 1)
            for column, name in enumerate(_ROW_BUTTONS, start=2):
                grid.addWidget(row.buttons[name], index, column)
        layout = QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addWidget(self.hint)
        layout.addLayout(grid)
        layout.addStretch(1)
        layout.addWidget(make_button_box(self, self.save_button, self.cancel_button))

    def values(self) -> dict[str, str]:
        """The text of every field by its legacy state key."""
        return {key: row.edit.text() for key, row in self.rows.items()}

    def _browse(self, key: str) -> None:
        row = self.rows[key]
        picked = self._p.browse(key, row.edit.text())
        if picked is not None:
            row.edit.setText(picked)

    def _auto(self, key: str) -> None:
        self.rows[key].edit.setText(self._p.detected(key))

    @override
    def accept(self) -> None:
        self._p.save(self.values())
        super().accept()

    @override
    def retranslate_ui(self) -> None:
        tr = self._translator.tr
        self.setWindowTitle(tr("dialog_file_paths"))
        self.heading.setText(tr("paths_editor_heading"))
        self.hint.setText(tr("paths_editor_hint"))
        for row in self.rows.values():
            label = tr(row.entry.label_key)
            row.label.setText(label)
            row.edit.setToolTip(tr("ui.paths.edit.tip", label=label))
            for name, button in row.buttons.items():
                set_button_text(button, tr(name), tr(f"ui.paths.{name}.tip", label=label))
        set_button_text(self.save_button, tr("save_file_paths"), tr("ui.paths.save.tip"))
        set_button_text(self.cancel_button, tr("cancel"), tr("ui.dialog.cancel.tip"))
