"""Importing a legacy ``dd_mod_loadout.json``: the order through the diff preview, then its extras.

The order half is the ordinary profile ladder (``resolve_document``) and review; the extras
(nicknames, categories, category memory) are applied only once the order was accepted (or needed
no change), as the legacy ``load_loadout`` did in one go (``legacy_loadout.py``).
"""

import dataclasses
from collections.abc import Mapping
from typing import TYPE_CHECKING

from src.core.ids import ModId
from src.core.loadorder_file import LegacyLoadoutExtras, LoadOrderDocument, resolve_document
from src.ui import controller_scan as scanning
from src.ui.controller_tools import is_assigned, remember

if TYPE_CHECKING:
    from src.ui.controller import MainController


def _collapse(text: str) -> str:
    return " ".join(text.split())


class LoadoutFlow:
    def __init__(self, controller: MainController) -> None:
        self._c = controller

    def import_legacy(self, doc: LoadOrderDocument, extras: LegacyLoadoutExtras) -> None:
        """Preview and commit the loadout's order, then apply its extras (a rejected preview
        applies nothing)."""
        c = self._c
        if not c.session.order.entries:
            c.post("ui.notice.no_mods_loaded", "warning")
            return
        result = resolve_document(doc, c.mods(), c.order())
        if result.unresolved:
            c.post("ui.notice.import_unmatched", "warning", count=len(result.unresolved))
        if result.order != c.order() and not c.review_and_commit(
            result.order, "ui.title.import_loadout", "ui.undo.import_loadout"
        ):
            return
        by_folder = {doc.entries[index].folder or "": mod for index, mod in result.matched}
        self._apply_extras(extras, by_folder)

    def _apply_extras(self, extras: LegacyLoadoutExtras, by_folder: Mapping[str, ModId]) -> None:
        c = self._c
        s = c.session
        categories = self._categories(extras.categories, by_folder)
        nicknames = self._nicknames(extras.nicknames, by_folder)
        s.pending.memory.update(extras.category_memory)
        s.doc = dataclasses.replace(
            s.doc,
            categories=dict(s.categories),
            nicknames={**s.doc.nicknames, **nicknames},
        )
        s.tiers = scanning.build_tiers(s.table, s.mods, s.categories, s.resolved)
        c.flush()  # the rows read nicknames from the saved document
        c.rebuild()
        c.validate()
        c.post(
            "ui.notice.loadout_imported",
            categories=len(categories),
            nicknames=len(nicknames),
        )

    def _categories(
        self, wanted: Mapping[str, str], by_folder: Mapping[str, ModId]
    ) -> dict[ModId, str]:
        s = self._c.session
        assigned = {
            by_folder[key]: category
            for key, category in wanted.items()
            if key in by_folder and is_assigned(category)
        }
        s.categories.update(assigned)
        s.pending.categories.update(assigned)
        remember(s, assigned)
        return assigned

    def _nicknames(
        self, wanted: Mapping[str, str], by_folder: Mapping[str, ModId]
    ) -> dict[ModId, str]:
        cleaned = {
            by_folder[key]: _collapse(text)
            for key, text in wanted.items()
            if key in by_folder and _collapse(text)
        }
        self._c.session.pending.nicknames.update(cleaned)
        return cleaned
