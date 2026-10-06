"""Order edits of the controller: the guarded commit path, undo/redo and auto-sort."""

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from src.core.ids import ModId
from src.core.load_order import LoadOrder, MoveOp
from src.core.sorting import auto_sort
from src.ui.catalog import order_diff_vm
from src.ui.undo import OrderCommand

if TYPE_CHECKING:
    from src.ui.controller import MainController


class EditFlows:
    """Every gesture ends in :meth:`commit`, the single place the active-save guard runs."""

    def __init__(self, controller: MainController) -> None:
        self._c = controller

    # ------------------------------------------------------------------ guard + commit

    def confirm_disable(self, ids: Iterable[ModId]) -> bool:
        """Ask before disabling mods the selected save currently applies."""
        c = self._c
        s = c.session
        leaving = set(ids)
        wanted = [mod for mod in s.order.active() if mod in leaving]
        save = s.save_path
        if not wanted or save is None or not save.is_file():
            return True
        applied = set(c.services.slots.applied_entries(save))
        known = c.identity_map()
        hits = [mod for mod in wanted if known.get(mod) in applied]
        if not hits:
            return True
        if c.prompter is None:
            return False
        rows = c.rows()
        titles = [rows[mod].title if mod in rows else str(mod) for mod in hits]
        return c.prompter.confirm_disable_active(titles, c.slot_label())

    def commit(self, after: LoadOrder, undo_key: str) -> bool:
        """Push one undo command for ``after``; refused when the guard says no."""
        c = self._c
        before = c.session.order
        if after == before:
            return False
        if not self.confirm_disable(before.enabled - after.enabled):
            return False
        return c.undo_stack.push_order_change(before, after, c.tr(undo_key))

    def review_and_commit(self, after: LoadOrder, title_key: str, undo_key: str) -> bool:
        """Show the diff preview of ``after`` and commit it when accepted."""
        c = self._c
        before = c.session.order
        if after == before:
            c.post("ui.notice.no_change")
            return False
        if c.prompter is None:
            return False
        diff = order_diff_vm(before, after, c.titles())
        if not c.prompter.review_order_change(diff, title_key):
            return False
        return self.commit(after, undo_key)

    # ------------------------------------------------------------------ gestures

    def move(self, ids: Sequence[ModId], op: MoveOp) -> None:
        self.commit(self._c.session.order.move(frozenset(ids), op), "ui.undo.move")

    def move_to(self, ids: Sequence[ModId], row: int) -> None:
        self.commit(self._c.session.order.move_to(frozenset(ids), row), "ui.undo.move")

    def enable(self, ids: Sequence[ModId], at_row: int | None) -> None:
        order = self._c.session.order
        known = [mod for mod in ids if mod in order.entries]
        self.commit(order.enable(known, at_row), "ui.undo.enable")

    def disable(self, ids: Sequence[ModId]) -> None:
        self.commit(self._c.session.order.disable(frozenset(ids)), "ui.undo.disable")

    def forget_missing(self, ids: Sequence[ModId]) -> None:
        """Drop missing mods from the order: only on request, and only after a confirmation."""
        c = self._c
        s = c.session
        gone = frozenset(mod for mod in ids if mod in s.missing)
        if not gone or c.prompter is None:
            return
        if c.prompter.confirm("ui.prompt.forget_missing", count=len(gone)):
            self.commit(s.order.forget(gone), "ui.undo.forget")

    # ------------------------------------------------------------------ undo / redo

    def step(self, *, forward: bool) -> None:
        """Undo or redo one command; a step that would disable applied mods runs the guard."""
        c = self._c
        stack = c.undo_stack
        if not (stack.canRedo() if forward else stack.canUndo()):
            return
        command = stack.command(stack.index() if forward else stack.index() - 1)
        if isinstance(command, OrderCommand):
            target = command.after if forward else command.before
            if not self.confirm_disable(c.session.order.enabled - target.enabled):
                return
        if forward:
            stack.redo()
        else:
            stack.undo()

    # ------------------------------------------------------------------ auto-sort

    def auto_sort(self) -> None:
        c = self._c
        s = c.session
        result = auto_sort(
            s.order,
            tier_weight=lambda mod: c.tier_of(mod).weight,
            edges=s.resolved.edges,
            direction=c.priority().direction,
        )
        if self.review_and_commit(result.order, "ui.title.auto_sort", "ui.undo.auto_sort"):
            c.post("ui.notice.sorted", moved=len(result.changes))
