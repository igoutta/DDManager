"""Apply order to local mod folders: plan, preview, rename in a worker, re-key the state, rescan.

The rename is the only destructive disk operation of the app besides restoring a save, so it
confirms through the prompter (the preview dialog), runs off the GUI thread and is all-or-nothing
(:class:`~src.services.folder_renamer.FolderRenamer` rolls back).  Folder names are mod ids, so
after a successful rename every state key that carries a mod id is re-keyed through
``RenamePlan.rekey`` and written immediately; only then is the mods folder rescanned.
"""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.findings import Severity
from src.core.folder_order import RenamePlan, plan_folder_renames
from src.core.identity import category_memory_keys
from src.core.ids import ModId, SourceKind
from src.core.load_order import LoadOrder
from src.services.errors import RenameFailedError
from src.services.folder_renamer import RenameResult
from src.services.ports import CancelToken
from src.ui.catalog import finding_message
from src.ui.presenters.tools_dto import RenamePreviewVM, RenameRowVM

if TYPE_CHECKING:
    from src.ui.controller import MainController
    from src.ui.session import Session


@dataclass(frozen=True, slots=True)
class RenameOutcome:
    """What the worker returns: the result, or the typed failure (never both)."""

    result: RenameResult | None = None
    error: RenameFailedError | None = None


def rekey_order(order: LoadOrder, rekey: Mapping[ModId, ModId]) -> LoadOrder:
    """``order`` with renamed entries; a new name that is already an entry merges into it."""
    entries = tuple(dict.fromkeys(rekey.get(mod, mod) for mod in order.entries))
    enabled = frozenset(rekey.get(mod, mod) for mod in order.enabled)
    return LoadOrder(entries, enabled)


def _rekeyed(mods: frozenset[ModId], rekey: Mapping[ModId, ModId]) -> frozenset[ModId]:
    return frozenset(rekey.get(mod, mod) for mod in mods)


def _moved(values: Mapping[ModId, str], rekey: Mapping[ModId, ModId]) -> dict[ModId, str | None]:
    """Pending updates that carry ``values`` from old ids to new ones.

    Every old id is unassigned first and every new id assigned after, so two folders that
    trade names (a swap) end up with each other's value instead of losing one.
    """
    kept = {old: values[old] for old in rekey if old in values}
    updates: dict[ModId, str | None] = dict.fromkeys(kept)
    updates.update({rekey[old]: value for old, value in kept.items()})
    return updates


def rekey_pending(s: Session, rekey: Mapping[ModId, ModId]) -> None:
    """Move every per-mod state value from the old id to the new one (as pending changes)."""
    doc = s.doc
    s.pending.categories.update(_moved(s.categories, rekey))
    s.pending.nicknames.update(_moved(doc.nicknames, rekey))
    for old, new in rekey.items():
        category = s.categories.get(old)
        info = s.mods.get(old)
        if category and info is not None:
            keys = category_memory_keys(dataclasses.replace(info, id=new))
            s.pending.memory.update(dict.fromkeys(keys, category))
    attempted = doc.auto_category_attempted
    renamed = {old for old in rekey if old in attempted}
    after = _rekeyed(attempted, rekey)
    s.pending.attempted |= {rekey[old] for old in renamed}
    s.pending.unattempted |= renamed - after  # the old names that no folder carries any more
    s.categories = {rekey.get(mod, mod): value for mod, value in s.categories.items()}
    s.doc = dataclasses.replace(
        s.doc,
        categories=dict(s.categories),
        nicknames={rekey.get(mod, mod): text for mod, text in doc.nicknames.items()},
        auto_category_attempted=after,
    )


class ApplyOrderFlow:
    """Tools > Apply order to local mod folders."""

    def __init__(self, controller: MainController) -> None:
        self._c = controller

    # ------------------------------------------------------------------ plan and preview

    def start(self) -> None:
        c = self._c
        s = c.session
        if not s.order.entries:
            c.post("ui.notice.no_mods_loaded", "warning")
            return
        if s.busy_text:  # a scan or another rename is running: the folders must not move under it
            c.post("ui.notice.busy", "warning")
            return
        if not c.flush():  # settle unsaved edits first: the plan depends on the current order
            return
        plan = plan_folder_renames(s.order, s.mods)
        blocking = [f for f in plan.findings if f.severity >= Severity.ERROR]
        if blocking:
            details = "\n".join(finding_message(f, c.tr, c.has) for f in blocking)
            c.prompter_error("ui.error.apply_blocked", details)
        elif not plan.steps:
            local = any(info.kind is SourceKind.LOCAL for info in s.mods.values())
            c.post("ui.notice.apply_nothing" if local else "ui.notice.apply_no_local")
        else:
            self._review(plan)

    def _review(self, plan: RenamePlan) -> None:
        prompter = self._c.prompter
        if prompter is not None and prompter.review_rename(self._preview(plan)):
            self._execute(plan)

    def _preview(self, plan: RenamePlan) -> RenamePreviewVM:
        c = self._c
        s = c.session
        titles = c.titles()
        rows = tuple(
            RenameRowVM(step.mod, titles.get(step.mod, str(step.mod)), step.old_name, step.new_name)
            for step in plan.steps
        )
        skipped = sum(
            1
            for mod in s.order.entries
            if (info := s.mods.get(mod)) is not None and info.kind is SourceKind.WORKSHOP
        )
        warnings = tuple(finding_message(f, c.tr, c.has) for f in plan.findings)
        root = s.install.primary_mods_dir if s.install is not None else None
        return RenamePreviewVM(rows, root, skipped, warnings)

    # ------------------------------------------------------------------ execute

    def _execute(self, plan: RenamePlan) -> None:
        c = self._c
        s = c.session
        renamer = c.services.renamer
        locations = {step.mod: Path(s.mods[step.mod].path) for step in plan.steps}
        primary = s.install.primary_mods_dir if s.install is not None else None
        root = primary if primary is not None else Path(s.doc.settings.mods_path)

        def work(_token: CancelToken) -> RenameOutcome:
            try:
                return RenameOutcome(result=renamer.execute(plan, root, locations=locations))
            except RenameFailedError as exc:
                return RenameOutcome(error=exc)

        c.run_task(work, self._finished, busy_key="ui.busy.renaming")

    def _finished(self, outcome: RenameOutcome) -> None:
        if outcome.error is not None:
            self._failed(outcome.error)
        elif outcome.result is not None:
            self._renamed(outcome.result)

    def _renamed(self, result: RenameResult) -> None:
        c = self._c
        s = c.session
        rekey_pending(s, result.rekey)
        s.order = rekey_order(s.order, result.rekey)
        c.undo_stack.clear()  # every command carries pre-rename mod ids
        c.select(())
        c.flush()
        c.post("ui.notice.apply_done", count=len(result.renamed))
        c.rescan()

    def _failed(self, error: RenameFailedError) -> None:
        c = self._c
        stuck = error.details.get("stuck")
        folders = [str(item) for item in stuck] if isinstance(stuck, list) else []
        rolled_back = bool(error.details.get("rolled_back")) and not folders
        tail = (
            c.tr("ui.error.rename_rolled_back")
            if rolled_back
            else c.tr("ui.error.rename_stuck", folders="\n".join(folders))
        )
        c.prompter_error("ui.error.rename_failed", f"{error.message}\n\n{tail}")
        if not rolled_back:
            c.rescan()
