"""The base of the management dialogs: they re-label themselves when the language changes."""

from PySide6.QtWidgets import QDialog, QWidget

from src.ui.dialogs.common import tip_chrome
from src.ui.i18n import Translator


class LiveDialog(QDialog):
    """A dialog that calls :meth:`retranslate_ui` on ``Translator.languageChanged``.

    Subclasses build their widgets, then call ``self.retranslate_ui()`` once; the connection is
    dropped with the dialog (Qt disconnects the slots of a destroyed receiver).  After every
    re-translation the generic tooltips of Qt's own buttons (see :func:`tip_chrome`) follow too.
    """

    def __init__(self, translator: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._translator = translator
        translator.languageChanged.connect(self._on_language)

    @property
    def translator(self) -> Translator:
        return self._translator

    def _on_language(self, _code: str) -> None:
        self.retranslate_ui()
        tip_chrome(self, self._translator.tr)

    def retranslate_ui(self) -> None:
        """Set every visible text and tooltip from the catalog (override)."""
        raise NotImplementedError
