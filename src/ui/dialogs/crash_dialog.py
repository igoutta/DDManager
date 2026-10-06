"""The crash dialog: details, copy, open the log folder, continue or quit."""

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from src.ui.dialogs.common import button_row, finish, make_button
from src.ui.i18n import Translator
from src.ui.theme.theme import set_role


class CrashDialog(QDialog):
    """``Quit`` rejects, ``Continue`` accepts; the details are selectable and copyable."""

    def __init__(
        self,
        title: str,
        details: str,
        translator: Translator,
        log_dir: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        tr = translator.tr
        self._details = details
        self._log_dir = log_dir
        self.setObjectName("dialog_crash")
        layout = QVBoxLayout(self)
        heading = QLabel(tr("ui.crash.heading", title=title))
        heading.setWordWrap(True)
        set_role(heading, "error")
        self.text = QPlainTextEdit(details, self)
        self.text.setReadOnly(True)
        self.copy_button = make_button(self, tr("ui.crash.copy"), tr("ui.crash.copy.tip"))
        self.logs_button = make_button(self, tr("ui.crash.logs"), tr("ui.crash.logs.tip"))
        self.continue_button = make_button(
            self, tr("ui.crash.continue"), tr("ui.crash.continue.tip")
        )
        self.quit_button = make_button(
            self, tr("ui.crash.quit"), tr("ui.crash.quit.tip"), role="danger"
        )
        self.logs_button.setEnabled(log_dir is not None)
        self.copy_button.clicked.connect(self._copy)
        self.logs_button.clicked.connect(self._open_logs)
        self.continue_button.clicked.connect(self.accept)
        self.quit_button.clicked.connect(self.reject)
        layout.addWidget(heading)
        layout.addWidget(self.text, 1)
        layout.addLayout(
            button_row(self.copy_button, self.logs_button, self.continue_button, self.quit_button)
        )
        finish(self, tr("ui.crash.title"), 720, 440, tr)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._details)

    def _open_logs(self) -> None:
        if self._log_dir is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._log_dir)))
