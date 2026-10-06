"""Preview of "Apply order to local mod folders": old and new folder names before any rename."""

from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget

from src.ui.dialogs.common import (
    finish,
    make_button,
    make_button_box,
    make_table,
    set_button_text,
    set_cell,
)
from src.ui.i18n import Translator
from src.ui.presenters.tools_dto import RenamePreviewVM
from src.ui.theme.theme import set_role
from src.ui.widgets.actions import IconSet


class ApplyOrderDialog(QDialog):
    """Accepting means "rename these folders now"; cancelling changes nothing."""

    def __init__(
        self,
        vm: RenamePreviewVM,
        translator: Translator,
        icons: IconSet,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = vm
        self._tr = translator
        self.setObjectName("dialog_apply_order")
        layout = QVBoxLayout(self)
        self.summary = QLabel(self)
        set_role(self.summary, "heading")
        self.root_label = self._muted_label()
        self.table = make_table(self, ["", "", ""])
        self._fill()
        self.skipped_label = self._muted_label()
        self.warnings = QListWidget(self)
        self.warnings.setMaximumHeight(90)
        self.warnings.addItems(list(vm.warnings))
        self.note = self._muted_label()
        self.apply_button = make_button(self, "", "", role="danger")
        self.apply_button.setIcon(icons.get("folder", "amber"))
        self.cancel_button = make_button(self, "", "")
        layout.addWidget(self.summary)
        layout.addWidget(self.root_label)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.skipped_label)
        layout.addWidget(self.warnings)
        layout.addWidget(self.note)
        layout.addWidget(make_button_box(self, self.apply_button, self.cancel_button))
        self.retranslate_ui()
        translator.languageChanged.connect(self.retranslate_ui)
        finish(self, translator.tr("ui.apply.title"), 760, 600, translator.tr)

    def _muted_label(self) -> QLabel:
        label = QLabel(self)
        label.setWordWrap(True)
        set_role(label, "muted")
        return label

    def _fill(self) -> None:
        self.table.setRowCount(len(self._vm.rows))
        for row, entry in enumerate(self._vm.rows):
            set_cell(self.table, row, 0, entry.title, f"{entry.title}\n{entry.mod_id}")
            set_cell(self.table, row, 1, entry.old_name)
            set_cell(self.table, row, 2, entry.new_name)
        self.table.resizeColumnsToContents()

    def retranslate_ui(self) -> None:
        tr = self._tr.tr
        vm = self._vm
        self.setWindowTitle(tr("ui.apply.title"))
        self.summary.setText(tr("ui.apply.summary", count=vm.count))
        self.root_label.setText(tr("ui.apply.root", path=vm.root) if vm.root else "")
        self.root_label.setVisible(vm.root is not None)
        self.table.setHorizontalHeaderLabels(
            [tr("ui.apply.col.mod"), tr("ui.apply.col.old"), tr("ui.apply.col.new")]
        )
        self.skipped_label.setText(tr("ui.apply.skipped", count=vm.skipped_workshop))
        self.skipped_label.setVisible(vm.skipped_workshop > 0)
        self.warnings.setVisible(bool(vm.warnings))
        self.note.setText(tr("ui.apply.note"))
        self._label(self.apply_button, "ui.apply.confirm")
        self._label(self.cancel_button, "ui.dialog.cancel")

    def _label(self, button: QPushButton, key: str) -> None:
        set_button_text(button, self._tr.tr(key), self._tr.tr(f"{key}.tip"))
