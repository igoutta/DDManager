"""The plugin approval dialog: user plugins / rule modules that are waiting for a decision.

Shown at start-up when plugins are enabled and some file is new or changed.  Approving pins the
file's sha256; the code runs at the next start, never before.
"""

from typing import TYPE_CHECKING, override

from PySide6.QtWidgets import QLabel, QMessageBox, QVBoxLayout, QWidget

from src.ui.dialogs.common import button_row, finish, make_button, set_button_text
from src.ui.dialogs.live_dialog import LiveDialog
from src.ui.dialogs.trust_table import (
    fill_trust_table,
    new_trust_table,
    retitle_trust_table,
    selected_file,
)
from src.ui.i18n import Translator
from src.ui.theme.theme import set_role
from src.ui.widgets.actions import IconSet

if TYPE_CHECKING:
    from src.ui.presenters.trust import TrustFileVM, TrustPresenter

_PENDING = frozenset({"not_approved", "changed"})


class PluginApprovalDialog(LiveDialog):
    def __init__(
        self,
        presenter: TrustPresenter,
        translator: Translator,
        icons: IconSet,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(translator, parent)
        self._p = presenter
        self._icons = icons
        self._rows: list[TrustFileVM] = []
        self.setObjectName("dialog_plugin_approval")
        self.heading = QLabel(self)
        set_role(self.heading, "heading")
        self.intro = QLabel(self)
        self.intro.setWordWrap(True)
        self.table = new_trust_table(self, translator, with_kind=True)
        self.security_note = QLabel(self)
        self.security_note.setWordWrap(True)
        set_role(self.security_note, "warning")
        self.approve_button = make_button(self, "approve", "approve.tip", role="primary")
        self.approve_all_button = make_button(self, "approve_all", "approve_all.tip")
        self.close_button = make_button(self, "close", "close.tip")
        layout = QVBoxLayout(self)
        for widget in (self.heading, self.intro):
            layout.addWidget(widget)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.security_note)
        layout.addLayout(
            button_row(self.approve_button, self.approve_all_button, self.close_button)
        )
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.approve_button.clicked.connect(self._approve)
        self.approve_all_button.clicked.connect(self._approve_all)
        self.close_button.clicked.connect(self.accept)
        presenter.changed.connect(self.refresh)
        self.retranslate_ui()
        finish(self, self.windowTitle(), 780, 420, translator.tr)

    def refresh(self) -> None:
        self._rows = self._p.records()
        fill_trust_table(self.table, self._rows, self._translator, with_kind=True)
        self._update_buttons()

    def _update_buttons(self) -> None:
        row = selected_file(self.table, self._rows)
        self.approve_button.setEnabled(row is not None and row.status in _PENDING)
        self.approve_all_button.setEnabled(any(r.status in _PENDING for r in self._rows))

    def _approve(self) -> None:
        row = selected_file(self.table, self._rows)
        if row is not None:
            self._p.approve(row.kind, row.name, expected=row.sha256 or None)

    def _approve_all(self) -> None:
        tr = self._translator.tr
        count = sum(1 for row in self._rows if row.status in _PENDING)
        answer = QMessageBox.question(
            self, tr("ui.trust.approve_all"), tr("ui.trust.approve_all_confirm", count=count)
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._p.approve_pending()

    @override
    def retranslate_ui(self) -> None:
        tr = self._translator.tr
        self.setWindowTitle(tr("ui.trust.dialog_title"))
        self.heading.setText(tr("ui.trust.heading"))
        self.intro.setText(tr("ui.trust.intro"))
        self.security_note.setText(tr("ui.trust.security_note"))
        self.table.setToolTip(tr("ui.trust.table.tip"))
        retitle_trust_table(self.table, self._translator, with_kind=True)
        set_button_text(self.approve_button, tr("ui.trust.approve"), tr("ui.trust.approve.tip"))
        set_button_text(
            self.approve_all_button, tr("ui.trust.approve_all"), tr("ui.trust.approve_all.tip")
        )
        set_button_text(self.close_button, tr("ui.trust.later"), tr("ui.trust.later.tip"))
        self.refresh()
