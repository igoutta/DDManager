"""Profiles presenter: save slots, load-order profiles and backups behind the manager dialog."""

import builtins
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

from src.__about__ import __version__
from src.core.ids import ModId, SaveIdentity
from src.core.load_order import LoadOrder
from src.core.loadorder_document import document_from_order
from src.core.loadorder_resolve import resolve_document
from src.services.errors import ServiceError
from src.services.save_slots import SaveSlot
from src.ui.presenters.backups import BackupsPresenter
from src.ui.presenters.dto import BackupVM, ProfileVM, SlotVM

if TYPE_CHECKING:
    from src.ui.controller import MainController

_DATE_FORMAT = "%Y-%m-%d %H:%M"


def order_from_identities(
    entries: Sequence[SaveIdentity], mods: dict[ModId, SaveIdentity], base: LoadOrder
) -> tuple[LoadOrder, int]:
    """An order whose enabled mods are the ones whose identity is in ``entries`` (in that order).

    Returns the order and the number of save entries no installed mod matches.
    """
    by_identity: dict[SaveIdentity, ModId] = {}
    for mod, identity in mods.items():
        by_identity.setdefault(identity, mod)
    matched: list[ModId] = []
    unmatched = 0
    for entry in entries:
        mod = by_identity.get(entry)
        if mod is None or mod in matched:
            unmatched += 1
        else:
            matched.append(mod)
    rest = [mod for mod in base.entries if mod not in matched]
    return LoadOrder((*matched, *rest), frozenset(matched)), unmatched


class ProfilesPresenter(QObject):
    def __init__(self, controller: MainController) -> None:
        super().__init__(controller)
        self._c = controller
        self._backups = BackupsPresenter(controller)

    # ------------------------------------------------------------------ slots

    def _slot_vm(self, slot: SaveSlot) -> SlotVM:
        c = self._c
        try:
            applied = len(c.services.slots.applied_entries(slot.save_path))
        except ServiceError:
            applied = 0
        date = slot.date_time or (slot.mtime.strftime(_DATE_FORMAT) if slot.mtime else "")
        return SlotVM(
            path=slot.save_path,
            label=c.slot_text(slot.number, None, slot.save_path),
            date_text=date,
            week_text="" if slot.week is None else str(slot.week),
            applied_text=str(applied),
            active=slot.save_path == c.save_path(),
        )

    def _known_slots(self) -> Sequence[SaveSlot]:
        """The detected slots, or the configured save alone while no scan has run yet."""
        slots = self._c.slot_list()
        path = self._c.save_path()
        if slots or path is None:
            return slots
        try:
            return self._c.services.slots.slots([path])
        except ServiceError:
            return ()

    def slots(self) -> builtins.list[SlotVM]:
        return [self._slot_vm(slot) for slot in self._known_slots()]

    def slot_choices(self) -> builtins.list[tuple[str, Path]]:
        """``(label, path)`` for the toolbar combo."""
        return [
            (self._c.slot_text(s.number, s.week, s.save_path), s.save_path)
            for s in self._c.slot_list()
        ]

    def use_slot(self, path: Path) -> None:
        self._c.use_save(path)

    def import_order_from_save(self, path: Path) -> None:
        c = self._c
        entries = c.services.slots.applied_entries(path)
        identities = {mod: info.save_identity for mod, info in c.mods().items()}
        after, unmatched = order_from_identities(entries, identities, c.order())
        if unmatched:
            c.post("ui.notice.import_unmatched", "warning", count=unmatched)
        c.review_and_commit(after, "ui.title.import_save", "ui.undo.import_save")

    def open_slot_folder(self, path: Path) -> None:
        self._c.open_path(path.parent)

    def open_backup_folder(self) -> None:
        self._c.open_backup_folder()

    def choose_save_file(self) -> None:
        self._c.settings.choose_save_file()

    def choose_mods_folder(self) -> None:
        self._c.settings.choose_mods_folder()

    # ------------------------------------------------------------------ profiles

    def _attempt[T](self, action: Callable[[], T]) -> T | None:
        try:
            return action()
        except ServiceError as exc:
            self._c.report_error(exc)
            return None

    def _succeeded(self, action: Callable[[], object]) -> bool:
        """Run a void action; True unless it raised a typed error (already reported)."""
        try:
            action()
        except ServiceError as exc:
            self._c.report_error(exc)
            return False
        return True

    def profiles(self) -> builtins.list[ProfileVM]:
        result: builtins.list[ProfileVM] = []
        for summary in self._c.services.profiles.list():
            created = summary.created_at.strftime(_DATE_FORMAT) if summary.created_at else ""
            problem = summary.findings[0].message if summary.findings else ""
            result.append(
                ProfileVM(
                    summary.name,
                    self._c.tr("ui.profiles.count", count=summary.entry_count),
                    created,
                    problem,
                )
            )
        return result

    def save_profile_as(self, name: str) -> bool:
        c = self._c
        tiers = {mod: c.tier_of(mod).id for mod in c.order().entries}
        doc = document_from_order(
            c.order(),
            c.mods(),
            name=name.strip(),
            priority=c.priority(),
            created_with=f"ddmanager {__version__}",
            created_at=c.services.clock.now(),
            tiers=tiers,
            include_disabled=True,
        )
        saved = self._attempt(lambda: c.services.profiles.save(doc))
        if saved is not None:
            c.post("ui.notice.profile_saved", name=doc.name)
        return saved is not None

    def apply_profile(self, name: str) -> None:
        c = self._c
        doc = self._attempt(lambda: c.services.profiles.load(name))
        if doc is None:
            return
        result = resolve_document(doc, c.mods(), c.order())
        if result.unresolved:
            c.post("ui.notice.import_unmatched", "warning", count=len(result.unresolved))
        c.review_and_commit(result.order, "ui.title.apply_profile", "ui.undo.profile")

    def import_file(self, path: Path) -> None:
        c = self._c
        imported = self._attempt(lambda: c.services.profiles.import_file(path))
        if imported is None:
            return
        doc, extras = imported
        # a 0.2 loadout re-imported under the same file name replaces the earlier copy
        saved = self._attempt(lambda: c.services.profiles.save(doc, overwrite=extras is not None))
        if saved is not None:
            c.post("ui.notice.profile_saved", name=doc.name)
        if extras is not None:
            c.tools.import_loadout_v02(doc, extras)

    def export(self, name: str, dest: Path) -> None:
        c = self._c
        doc = self._attempt(lambda: c.services.profiles.load(name))
        if doc is not None and self._succeeded(lambda: c.services.profiles.export(doc, dest)):
            c.post("ui.notice.profile_exported", name=name)

    def rename(self, old: str, new: str) -> bool:
        return self._attempt(lambda: self._c.services.profiles.rename(old, new.strip())) is not None

    def delete(self, name: str) -> bool:
        return self._succeeded(lambda: self._c.services.profiles.delete(name))

    # ------------------------------------------------------------------ backups

    def backups_for_active(self) -> builtins.list[BackupVM]:
        return self._backups.listing()

    def restore(self, path: Path, on_done: Callable[[], None] | None = None) -> None:
        self._backups.restore(path, on_done)
