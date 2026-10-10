"""Debounced writes of ``mod_state.json`` and the external-change conflict flow."""

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer

from src.core.tiers import TierTable
from src.ui import controller_state as persistence

if TYPE_CHECKING:
    from src.ui.controller import MainController

SAVE_DELAY_MS = 500


class StateSync(QObject):
    def __init__(self, controller: MainController) -> None:
        super().__init__(controller)
        self._c = controller
        self._warned_read_only = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(SAVE_DELAY_MS)
        self.timer.timeout.connect(self.flush)

    def schedule(self) -> None:
        if persistence.is_dirty(self._c.session):
            self.timer.start()

    def flush(self) -> bool:
        """Write now; True when nothing is left unsaved or the user resolved a conflict."""
        self.timer.stop()
        c = self._c
        if not persistence.is_dirty(c.session):
            return True
        outcome = persistence.write_state(c.services.state, c.session)
        if outcome == "ok":
            c.emit_status()
            return True
        if outcome == "read_only":
            self._warn_read_only()
            return True
        return self._on_conflict()

    def _warn_read_only(self) -> None:
        if not self._warned_read_only:
            self._warned_read_only = True
            self._c.post("ui.notice.state_read_only", "error")

    def _on_conflict(self) -> bool:
        c = self._c
        c.session.conflict = True
        c.stateConflict.emit()
        c.emit_status()
        answer = c.prompter.resolve_state_conflict() if c.prompter else "cancel"
        if answer == "reload":
            self.reload()
        elif answer == "overwrite":
            self.keep_mine()
        return answer != "cancel"

    def reload(self) -> None:
        """Adopt the file as it is on disk (dropping unsaved edits) and rebuild everything."""
        c = self._c
        s = c.session
        snapshot = c.services.state.load()
        s.doc, s.fingerprint = snapshot.doc, snapshot.fingerprint
        s.pending.clear()
        s.conflict = False
        s.categories = dict(snapshot.doc.categories)
        s.order = snapshot.doc.order.reconcile(s.mods).order
        doc = snapshot.doc
        s.table = TierTable.from_categories(doc.category_order, doc.custom_categories)
        c.reclassify()
        c.undo_stack.clear()
        c.rebuild()
        c.validate()

    def keep_mine(self) -> None:
        """Overwrite the changed file with this session's order and pending changes."""
        c = self._c
        outcome = persistence.write_state(c.services.state, c.session, rebase=True)
        if outcome == "ok":
            c.emit_status()
        elif outcome == "read_only":
            self._warn_read_only()
        else:
            c.post("ui.notice.state_conflict", "error")
