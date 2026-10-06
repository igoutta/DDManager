"""Dry-run preview of patching a save: diff, backup target, errors and risk acknowledgements."""

from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QListWidget, QVBoxLayout, QWidget

from src.core.findings import Severity
from src.ui.dialogs.common import finish, make_button, make_button_box, make_table, set_cell
from src.ui.i18n import Translator
from src.ui.ports import PatchDecision
from src.ui.theme.theme import set_role
from src.ui.viewmodels import PatchPreviewVM


class PatchPreviewDialog(QDialog):
    """The patch button stays disabled until every risk is acknowledged."""

    def __init__(
        self, vm: PatchPreviewVM, translator: Translator, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._vm = vm
        self._tr = translator
        self.setObjectName("dialog_patch_preview")
        layout = QVBoxLayout(self)
        tr = translator.tr
        heading = QLabel(tr("ui.patch.target", slot=vm.slot_label))
        set_role(heading, "heading")
        layout.addWidget(heading)
        layout.addWidget(self._path_label(tr("ui.patch.save_path", path=vm.save_path)))
        layout.addWidget(self._path_label(tr("ui.patch.backup_dir", path=vm.backup_dir)))
        layout.addWidget(QLabel(self._summary()))
        if vm.missing_count:
            missing = QLabel(tr("ui.patch.missing_excluded", count=vm.missing_count))
            missing.setWordWrap(True)
            set_role(missing, "warning")
            layout.addWidget(missing)
        layout.addWidget(self._diff_table(), 1)
        self.errors = self._findings_list(layout)
        self.ack_boxes = self._ack_boxes(layout)
        self.override_box = self._override_box(layout) if vm.blocking else None
        self.patch_button = make_button(
            self, tr("ui.patch.apply"), tr("ui.patch.apply.tip"), role="danger"
        )
        self.cancel_button = make_button(self, tr("ui.dialog.cancel"), tr("ui.dialog.cancel.tip"))
        layout.addWidget(make_button_box(self, self.patch_button, self.cancel_button))
        self._update_primary()
        finish(self, tr("ui.patch.title"), 760, 640, tr)

    @staticmethod
    def _path_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        set_role(label, "muted")
        return label

    def _error_count(self) -> int:
        return sum(1 for f in self._vm.findings if f.severity >= Severity.ERROR)

    def _summary(self) -> str:
        diff = self._vm.diff
        return self._tr.tr(
            "ui.patch.summary",
            before=len(self._vm.before),
            after=len(self._vm.after),
            added=diff.added,
            removed=diff.removed,
            moved=diff.moved_count,
        )

    def _diff_table(self) -> QWidget:
        tr = self._tr.tr
        table = make_table(
            self,
            [
                tr("ui.patch.col.change"),
                tr("ui.patch.col.entry"),
                tr("ui.patch.col.before"),
                tr("ui.patch.col.after"),
            ],
        )
        table.setRowCount(len(self._vm.diff.rows))
        for row, entry in enumerate(self._vm.diff.rows):
            if entry.old_rank is None:
                mark = "+"
            elif entry.new_rank is None:
                mark = "-"
            else:
                mark = "" if entry.old_rank == entry.new_rank else "~"
            set_cell(table, row, 0, mark)
            set_cell(table, row, 1, entry.title)
            set_cell(table, row, 2, "" if entry.old_rank is None else str(entry.old_rank))
            set_cell(table, row, 3, "" if entry.new_rank is None else str(entry.new_rank))
        return table

    def _findings_list(self, layout: QVBoxLayout) -> QListWidget | None:
        errors = [f for f in self._vm.findings if f.severity >= Severity.ERROR]
        if not errors:
            return None
        heading = QLabel(self._tr.tr("ui.patch.errors", count=len(errors)))
        set_role(heading, "error")
        listing = QListWidget(self)
        for finding in errors:
            listing.addItem(finding.message)
        listing.setMaximumHeight(120)
        layout.addWidget(heading)
        layout.addWidget(listing)
        return listing

    def _ack_boxes(self, layout: QVBoxLayout) -> dict[str, QCheckBox]:
        boxes: dict[str, QCheckBox] = {}
        for ack, key in self._vm.required_acks:
            box = QCheckBox(self._tr.tr(key), self)
            box.setToolTip(self._tr.tr("ui.patch.ack.tip"))
            box.toggled.connect(self._update_primary)
            layout.addWidget(box)
            boxes[ack] = box
        return boxes

    def _override_box(self, layout: QVBoxLayout) -> QCheckBox:
        tr = self._tr.tr
        box = QCheckBox(tr("ui.patch.override", count=self._error_count()), self)
        box.setToolTip(tr("ui.patch.override.tip"))
        box.toggled.connect(self._update_primary)
        layout.addWidget(box)
        return box

    def _override(self) -> bool:
        return self.override_box is not None and self.override_box.isChecked()

    def _update_primary(self) -> None:
        acked = all(box.isChecked() for box in self.ack_boxes.values())
        self.patch_button.setEnabled(acked and (not self._vm.blocking or self._override()))

    def decision(self) -> PatchDecision:
        """What the patch button would commit; ``proceed`` is False while a risk is unacknowledged.

        The prompter combines it with the dialog's result: a cancelled dialog never proceeds.
        """
        return PatchDecision(
            proceed=self.patch_button.isEnabled(),
            acknowledged=frozenset(a for a, box in self.ack_boxes.items() if box.isChecked()),
            override_errors=self._override(),
        )
