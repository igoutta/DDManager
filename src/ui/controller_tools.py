"""Tools of the controller that change the state quietly: Auto Categorize and the duplicate notice.

Both write through the debounced ``Session.pending`` changes and never touch the load order.
"""

import dataclasses
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from src.core.categories import PSEUDO_CATEGORIES
from src.core.classify import suggest_category
from src.core.findings import Finding
from src.core.identity import category_memory_keys
from src.core.ids import ModId
from src.rules.duplicate_identity import RULE_ID as DUPLICATE_RULE
from src.ui.controller_scan import build_tiers

if TYPE_CHECKING:
    from src.ui.controller import MainController
    from src.ui.session import Session

LOCAL_WORKSHOP_KEY: Final = "finding.core.duplicate_identity.local_workshop"
PREVIEW_GROUPS: Final = 3


def is_assigned(category: str | None) -> bool:
    """A category counts unless it is empty, ``Unassigned`` or ``All``."""
    return bool(category) and category not in PSEUDO_CATEGORIES


def remember(s: Session, categories: Mapping[ModId, str]) -> None:
    """Category memory of every identity key of the categorised mods."""
    for mod, category in categories.items():
        info = s.mods.get(mod)
        if info is not None:
            s.pending.memory.update(dict.fromkeys(category_memory_keys(info), category))


def auto_categorize(c: MainController) -> None:
    """Classify every mod that has no category; mods with no confident match stay unassigned."""
    s = c.session
    if not s.order.entries:
        c.post("ui.notice.no_mods_loaded", "warning")
        return
    assigned: dict[ModId, str] = {}
    ambiguous: list[ModId] = []
    for mod in s.order.entries:
        info = s.mods.get(mod)
        if info is None or is_assigned(s.categories.get(mod)):
            continue
        s.pending.attempted.add(mod)
        suggestion = suggest_category(info, nickname=s.doc.nicknames.get(mod))
        if suggestion:
            assigned[mod] = suggestion
        else:
            ambiguous.append(mod)
    s.categories.update(assigned)
    s.pending.categories.update(assigned)
    remember(s, assigned)
    s.doc = dataclasses.replace(
        s.doc,
        categories=dict(s.categories),
        auto_category_attempted=s.doc.auto_category_attempted | s.pending.attempted,
    )
    s.tiers = build_tiers(s.table, s.mods, s.categories, s.resolved)
    c.schedule_save()
    c.rebuild()
    c.validate()
    key = "ui.notice.auto_categorized_review" if ambiguous else "ui.notice.auto_categorized"
    c.post(key, assigned=len(assigned), ambiguous=len(ambiguous))


class DuplicateWatch:
    """One summary notice for local/Workshop copies of the same mod, after the first scan.

    The groups are the ``core.duplicate_identity`` findings of the local + Workshop kind (both
    copies active), read from the session when the first post-scan validation lands.
    """

    def __init__(self, controller: MainController) -> None:
        self._c = controller
        self._done = False

    def on_findings(self, *_args: object) -> None:
        c = self._c
        s = c.session
        if self._done or not s.mods:
            return
        self._done = True
        groups = [
            f
            for f in s.findings
            if f.rule_id == DUPLICATE_RULE and f.message_key == LOCAL_WORKSHOP_KEY
        ]
        if groups:
            c.post(
                "ui.notice.duplicates",
                "warning",
                count=len(groups),
                groups=self._groups_text(groups),
            )

    def _groups_text(self, groups: list[Finding]) -> str:
        tr = self._c.tr
        shown = []
        for finding in groups[:PREVIEW_GROUPS]:
            params = dict(finding.params)
            shown.append(
                tr(
                    "ui.notice.duplicates.group",
                    locals=params.get("locals", ""),
                    workshop=params.get("workshop", ""),
                )
            )
        text = "; ".join(shown)
        if len(groups) > PREVIEW_GROUPS:
            text += " " + tr("ui.notice.duplicates.more", count=len(groups) - PREVIEW_GROUPS)
        return text
