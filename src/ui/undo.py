"""Undo/redo of load-order changes as before/after snapshots."""

from typing import Protocol, override

from PySide6.QtCore import QObject
from PySide6.QtGui import QUndoCommand, QUndoStack

from src.core.load_order import LoadOrder


class OrderApplier(Protocol):
    """What a command needs from the controller."""

    def apply_order(self, order: LoadOrder) -> None: ...


class OrderCommand(QUndoCommand):
    """One undoable change: ``redo`` applies ``after``, ``undo`` applies ``before``."""

    def __init__(
        self, applier: OrderApplier, before: LoadOrder, after: LoadOrder, text: str
    ) -> None:
        super().__init__(text)
        self._applier = applier
        self._before = before
        self._after = after

    @property
    def before(self) -> LoadOrder:
        return self._before

    @property
    def after(self) -> LoadOrder:
        return self._after

    @override
    def redo(self) -> None:
        self._applier.apply_order(self._after)

    @override
    def undo(self) -> None:
        self._applier.apply_order(self._before)


class OrderUndoStack(QUndoStack):
    def __init__(self, applier: OrderApplier, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._applier = applier

    def push_order_change(self, before: LoadOrder, after: LoadOrder, text: str) -> bool:
        """Push one command; a no-op change (``before == after``) pushes nothing."""
        if before == after:
            return False
        self.push(OrderCommand(self._applier, before, after, text))
        return True
