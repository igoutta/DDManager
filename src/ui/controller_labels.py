"""Per-mod labels and the category layout: assign a category, set a nickname, commit the editor.

Every change lands in the session's pending state (one debounced write, never a partial one) and
the rows, tiers and findings are recomputed.  Built-in categories are ordinary names here; the
rules about what may be renamed or removed live in the categories presenter.
"""

import dataclasses
from collections.abc import Sequence
from typing import TYPE_CHECKING

from src.core.categories import (
    PSEUDO_CATEGORIES,
    CategoryEditorState,
    apply_category_editor_changes,
    category_color,
    get_categories,
    normalize_hex_color,
)
from src.core.display import display_name
from src.core.identity import category_memory_keys
from src.core.ids import ModId
from src.core.tiers import TierTable
from src.ui import controller_scan as scanning
from src.ui.catalog import category_label
from src.ui.presenters.labels import CategoryChoiceVM, NicknameVM
from src.ui.session import CategoryLayout
from src.ui.theme.tokens import TIER_TOKENS

if TYPE_CHECKING:
    from src.ui.controller import MainController

_CUSTOM_COLOR = TIER_TOKENS["custom"].color


def collapse(text: str) -> str:
    """The text with every whitespace run reduced to one space."""
    return " ".join(text.split())


class LabelFlows:
    def __init__(self, controller: MainController) -> None:
        self._c = controller

    # ------------------------------------------------------------------ assign a category

    def category_choices(self) -> tuple[CategoryChoiceVM, ...]:
        """Every assignable category in editor order with its display color."""
        c = self._c
        doc = c.session.doc
        names = get_categories(
            doc.category_order, doc.custom_categories, c.session.categories.values()
        )
        return tuple(
            CategoryChoiceVM(
                name,
                category_label(name, c.tr, c.has),
                category_color(name, doc.category_colors, _CUSTOM_COLOR),
            )
            for name in names
        )

    def set_category(self, ids: Sequence[ModId], name: str | None) -> int:
        """Assign ``name`` to ``ids`` (``None`` or a pseudo category unassigns); returns the count.

        The assignment and the remembered category
        of every identity key of the mod (so a re-installed copy is classified the same way).
        """
        c = self._c
        s = c.session
        target = None if not name or name in PSEUDO_CATEGORIES else name
        present = set(s.order.entries)
        known = [mod for mod in dict.fromkeys(ids) if mod in present]
        if not known:
            return 0
        for mod in known:
            self._assign(mod, target, remember=True)
        self._sync_doc()
        self._refresh()
        label = category_label(target, c.tr, c.has)
        c.post("ui.notice.category_set", count=len(known), category=label)
        return len(known)

    def _assign(self, mod: ModId, target: str | None, *, remember: bool) -> None:
        """One mod's category; ``remember`` also records it under every identity key of the mod."""
        s = self._c.session
        s.pending.categories[mod] = target
        if target is None:
            s.categories.pop(mod, None)
            s.pending.attempted.add(mod)
            return
        s.categories[mod] = target
        info = s.mods.get(mod)
        if remember and info is not None:
            s.pending.memory.update(dict.fromkeys(category_memory_keys(info), target))

    def _sync_doc(self, **changes: object) -> None:
        """Keep the session's view of the document in step with what is pending."""
        s = self._c.session
        s.doc = dataclasses.replace(s.doc, categories=dict(s.categories), **changes)

    def _refresh(self) -> None:
        c = self._c
        s = c.session
        s.tiers = scanning.build_tiers(s.table, s.mods, s.categories, s.resolved)
        c.schedule_save()
        c.rebuild()
        c.validate()

    # ------------------------------------------------------------------ nickname

    def nickname_vm(self, mod: ModId) -> NicknameVM | None:
        s = self._c.session
        info = s.mods.get(mod)
        if info is None:
            return None
        default = display_name(info, None)
        saved = collapse(s.doc.nicknames.get(mod, ""))
        return NicknameVM(mod, display_name(info, saved or None), default, saved, saved or default)

    def set_nickname(self, mod: ModId, text: str) -> bool:
        """Save ``text`` as the nickname of ``mod``; the default display name (or nothing) clears.

        Returns ``False`` when nothing changed.
        """
        c = self._c
        s = c.session
        info = s.mods.get(mod)
        if info is None:
            return False
        nickname = collapse(text)
        if nickname == display_name(info, None):
            nickname = ""
        if nickname == collapse(s.doc.nicknames.get(mod, "")):
            return False
        names = {key: value for key, value in s.doc.nicknames.items() if key != mod}
        if nickname:
            names[mod] = nickname
        s.pending.nicknames[mod] = nickname or None
        s.doc = dataclasses.replace(s.doc, nicknames=names)
        c.schedule_save()
        c.rebuild()
        c.select_requested([mod])
        if nickname:
            c.post("status_nickname_set", nickname=nickname)
        else:
            c.post("status_nickname_cleared")
        return True

    # ------------------------------------------------------------------ the category editor

    def editor_state(self) -> CategoryEditorState:
        """The editor's working copy: ordered, custom and discovered names, colors normalised."""
        s = self._c.session
        doc = s.doc
        colors = {
            name: normalized
            for name, color in doc.category_colors.items()
            if (normalized := normalize_hex_color(color))
        }
        return CategoryEditorState(
            categories=get_categories(
                doc.category_order, doc.custom_categories, s.categories.values()
            ),
            custom_categories=tuple(doc.custom_categories),
            category_colors=colors,
            renamed={},
            removed=(),
        )

    def commit_categories(self, state: CategoryEditorState) -> None:
        """Apply the editor's draft as one change."""
        c = self._c
        s = c.session
        memory = {**s.doc.category_memory, **s.pending.memory}
        changes = apply_category_editor_changes(
            state, assignments=dict(s.categories), category_memory=memory
        )
        s.pending.layout = CategoryLayout(
            changes.category_order,
            changes.custom_categories,
            changes.category_colors,
            changes.category_memory,
        )
        s.pending.memory.clear()
        for mod, category in changes.assignments.items():
            self._assign(mod, category, remember=False)
        s.table = TierTable.from_categories(changes.category_order, changes.custom_categories)
        self._sync_doc(
            category_order=changes.category_order,
            custom_categories=changes.custom_categories,
            category_colors=changes.category_colors,
            category_memory=changes.category_memory,
        )
        self._refresh()
        c.post("ui.notice.categories_updated")
