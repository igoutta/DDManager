"""One trust section of the settings dialog: the switch and the files of the plugin/rule folder."""

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QCheckBox, QGroupBox, QLabel, QPushButton, QVBoxLayout, QWidget

from src.ui.dialogs.common import button_row, make_button, set_button_text
from src.ui.dialogs.trust_table import (
    fill_trust_table,
    new_trust_table,
    retitle_trust_table,
    selected_file,
)
from src.ui.i18n import Translator
from src.ui.theme.theme import set_role

if TYPE_CHECKING:
    from src.ui.presenters.trust import Kind, TrustFileVM, TrustPresenter


class TrustSection(QGroupBox):
    """A switch (nothing runs while it is off) and the files with Approve / Revoke."""

    def __init__(
        self, presenter: TrustPresenter, kind: Kind, translator: Translator, parent: QWidget
    ) -> None:
        super().__init__(parent)
        self._p = presenter
        self._kind: Kind = kind
        self._translator = translator
        self._rows: list[TrustFileVM] = []
        self.setObjectName(f"trust_{kind}")
        self.enable_box = QCheckBox(self)
        self.enable_box.setObjectName(f"trust_enable_{kind}")
        self.folder_label = QLabel(self)
        set_role(self.folder_label, "muted")
        self.table = new_trust_table(self, translator, with_kind=False)
        self.approve_button: QPushButton = make_button(
            self, "approve", "approve.tip", role="primary"
        )
        self.revoke_button: QPushButton = make_button(self, "revoke", "revoke.tip")
        layout = QVBoxLayout(self)
        layout.addWidget(self.enable_box)
        layout.addWidget(self.folder_label)
        layout.addWidget(self.table, 1)
        layout.addLayout(button_row(self.approve_button, self.revoke_button))
        self.enable_box.toggled.connect(self._on_toggled)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.approve_button.clicked.connect(self._approve)
        self.revoke_button.clicked.connect(self._revoke)
        presenter.changed.connect(self.refresh)
        self.retranslate_ui()
        self.refresh()

    def refresh(self) -> None:
        self._rows = self._p.files(self._kind)
        fill_trust_table(self.table, self._rows, self._translator, with_kind=False)
        self.enable_box.blockSignals(True)  # noqa: FBT003
        self.enable_box.setChecked(self._p.enabled(self._kind))
        self.enable_box.blockSignals(False)  # noqa: FBT003
        self._update_buttons()

    def _update_buttons(self) -> None:
        row = selected_file(self.table, self._rows)
        self.approve_button.setEnabled(row is not None and row.status != "approved")
        self.revoke_button.setEnabled(row is not None and row.status in {"approved", "changed"})

    def _on_toggled(self, checked: bool) -> None:
        self._p.set_enabled(self._kind, on=checked)

    def _approve(self) -> None:
        row = selected_file(self.table, self._rows)
        if row is not None:
            self._p.approve(self._kind, row.name, expected=row.sha256 or None)

    def _revoke(self) -> None:
        row = selected_file(self.table, self._rows)
        if row is not None:
            self._p.revoke(self._kind, row.name)

    def retranslate_ui(self) -> None:
        tr = self._translator.tr
        kind = self._kind
        self.setTitle(tr(f"ui.trust.title.{kind}"))
        self.enable_box.setText(tr(f"ui.trust.enable.{kind}"))
        self.enable_box.setToolTip(tr(f"ui.trust.enable.{kind}.tip"))
        self.folder_label.setText(tr("ui.trust.folder", path=str(self._p.directory(kind))))
        self.table.setToolTip(tr("ui.trust.table.tip"))
        retitle_trust_table(self.table, self._translator, with_kind=False)
        set_button_text(self.approve_button, tr("ui.trust.approve"), tr("ui.trust.approve.tip"))
        set_button_text(self.revoke_button, tr("ui.trust.revoke"), tr("ui.trust.revoke.tip"))
        fill_trust_table(self.table, self._rows, self._translator, with_kind=False)
