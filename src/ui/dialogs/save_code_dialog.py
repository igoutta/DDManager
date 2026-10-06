"""The generated ``applied_ugcs_1_0`` block as copyable text (legacy "Generate Save Code")."""

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from src.ui.dialogs.common import button_row, finish, set_button_text
from src.ui.i18n import Translator
from src.ui.presenters.tools_dto import SaveCodeVM
from src.ui.theme.theme import set_role
from src.ui.widgets.actions import IconSet


class SaveCodeDialog(QDialog):
    """Read-only monospace text with a Copy button; the text is exactly ``vm.text``."""

    def __init__(
        self,
        vm: SaveCodeVM,
        translator: Translator,
        icons: IconSet,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = vm
        self._tr = translator
        self.setObjectName("dialog_save_code")
        layout = QVBoxLayout(self)
        self.heading = QLabel(self)
        self.heading.setWordWrap(True)
        set_role(self.heading, "heading")
        self.text = QPlainTextEdit(vm.text, self)
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        set_role(self.text, "mono")
        self.copied_label = QLabel(self)
        set_role(self.copied_label, "ok")
        self.copy_button = QPushButton(self)
        self.copy_button.setIcon(icons.get("patch"))
        self.copy_button.setAutoDefault(False)
        set_role(self.copy_button, "primary")
        self.close_button = QPushButton(self)
        self.close_button.setAutoDefault(False)
        self.copy_button.clicked.connect(self.copy_to_clipboard)
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(self.heading)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.copied_label)
        layout.addLayout(button_row(self.copy_button, self.close_button))
        self.retranslate_ui()
        translator.languageChanged.connect(self.retranslate_ui)
        finish(self, translator.tr("ui.savecode.title"), 760, 560, translator.tr)

    def copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setText(self._vm.text)
        self.copied_label.setText(self._tr.tr("ui.notice.copied"))

    def retranslate_ui(self) -> None:
        tr = self._tr.tr
        self.setWindowTitle(tr("ui.savecode.title"))
        self.heading.setText(tr("ui.savecode.heading", count=self._vm.count))
        set_button_text(self.copy_button, tr("ui.savecode.copy"), tr("ui.savecode.copy.tip"))
        set_button_text(self.close_button, tr("ui.dialog.close"), tr("ui.dialog.close.tip"))
        self.copied_label.setText("")
