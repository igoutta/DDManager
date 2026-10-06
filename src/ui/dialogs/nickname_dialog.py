"""The nickname dialog: one line of text; Enter saves (``dd2.py:7041-7150``)."""

from typing import TYPE_CHECKING, override

from PySide6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

from src.ui.dialogs.common import finish, make_button, make_button_box, set_button_text
from src.ui.dialogs.live_dialog import LiveDialog
from src.ui.i18n import Translator
from src.ui.theme.theme import set_role
from src.ui.widgets.actions import IconSet

if TYPE_CHECKING:
    from src.ui.presenters.labels import NicknameVM


class NicknameDialog(LiveDialog):
    """Starts from the saved nickname (else the default name); that name or nothing clears it."""

    def __init__(
        self,
        vm: NicknameVM,
        translator: Translator,
        icons: IconSet,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(translator, parent)
        self._vm = vm
        self._icons = icons
        self.setObjectName("dialog_nickname")
        self.title_label = QLabel(self)
        set_role(self.title_label, "heading")
        self.prompt = QLabel(self)
        self.edit = QLineEdit(vm.initial, self)
        self.hint = QLabel(self)
        self.hint.setWordWrap(True)
        set_role(self.hint, "muted")
        self.save_button = make_button(self, "save", "save.tip", role="primary")
        self.cancel_button = make_button(self, "cancel", "cancel.tip")
        layout = QVBoxLayout(self)
        for widget in (self.title_label, self.prompt, self.edit, self.hint):
            layout.addWidget(widget)
        layout.addWidget(make_button_box(self, self.save_button, self.cancel_button))
        # Enter in the line edit presses the default button: make that Save, not Cancel.
        self.cancel_button.setDefault(False)
        self.save_button.setDefault(True)
        self.edit.selectAll()
        self.edit.setFocus()
        self.retranslate_ui()
        finish(self, self.windowTitle(), 500, 190, translator.tr)

    def text(self) -> str:
        """The entered nickname with every whitespace run collapsed (``dd2.py:7086``)."""
        return " ".join(self.edit.text().split())

    @override
    def retranslate_ui(self) -> None:
        tr = self._translator.tr
        self.setWindowTitle(tr("dialog_set_nickname"))
        self.title_label.setText(self._vm.title)
        self.prompt.setText(tr("nickname"))
        self.edit.setToolTip(tr("ui.nickname.edit.tip", name=self._vm.default_name))
        self.hint.setText(tr("ui.nickname.hint", name=self._vm.default_name))
        set_button_text(self.save_button, tr("save"), tr("ui.dialog.save.tip"))
        set_button_text(self.cancel_button, tr("cancel"), tr("ui.dialog.cancel.tip"))
