"""The NEW highlight: a mod that appeared on disk keeps its pill for a while, then loses it.

``NEW_MOD_HIGHLIGHT_MS`` is the window (15 seconds).
Expiry re-renders the affected rows in place (``dataChanged`` through the models' diffing
publish path); nothing is re-sorted, so a drag during or after the window never promotes a mod.
"""

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QObject, QTimer

if TYPE_CHECKING:
    from src.ui.controller import MainController

NEW_MOD_HIGHLIGHT_MS: Final = 15000


class NewHighlight(QObject):
    """Owns the single-shot timer that clears ``Session.new_ids`` after the highlight window."""

    def __init__(self, controller: MainController) -> None:
        super().__init__(controller)
        self._c = controller
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(NEW_MOD_HIGHLIGHT_MS)
        self.timer.timeout.connect(self.expire)

    def start(self) -> None:
        """(Re)start the countdown after a scan; without new mods there is nothing to count."""
        if self._c.session.new_ids:
            self.timer.start()
        else:
            self.timer.stop()

    def expire(self) -> None:
        """Drop the pill of every new row in place."""
        self.timer.stop()
        s = self._c.session
        ids = s.new_ids
        if not ids:
            return
        s.new_ids = frozenset()
        self._c.rebuild_rows(ids)
