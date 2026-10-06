"""The setup report ("Check Setup"): copyable plain text, English by design."""

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from src.ui.dialogs.common import button_row, finish, set_button_text
from src.ui.i18n import Translator
from src.ui.presenters.tools_dto import DiagnosticsVM
from src.ui.theme.theme import set_role
from src.ui.widgets.actions import IconSet


class DiagnosticsDialog(QDialog):
    """Read-only report text with a Copy button; the text is exactly ``vm.text``."""

    def __init__(
        self,
        vm: DiagnosticsVM,
        translator: Translator,
        icons: IconSet,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = vm
        self._tr = translator
        self.setObjectName("dialog_diagnostics")
        layout = QVBoxLayout(self)
        self.heading = QLabel(self)
        self.heading.setWordWrap(True)
        set_role(self.heading, "muted")
        self.text = QPlainTextEdit(vm.text, self)
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        set_role(self.text, "mono")
        self.copied_label = QLabel(self)
        set_role(self.copied_label, "ok")
        self.copy_button = QPushButton(self)
        self.copy_button.setIcon(icons.get("info"))
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
        finish(self, translator.tr("ui.diag.title"), 720, 560, translator.tr)

    def copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setText(self._vm.text)
        self.copied_label.setText(self._tr.tr("ui.notice.copied"))

    def retranslate_ui(self) -> None:
        tr = self._tr.tr
        self.setWindowTitle(tr("ui.diag.title"))
        self.heading.setText(tr("ui.diag.heading"))
        set_button_text(self.copy_button, tr("ui.diag.copy"), tr("ui.diag.copy.tip"))
        set_button_text(self.close_button, tr("ui.dialog.close"), tr("ui.dialog.close.tip"))
        self.copied_label.setText("")
