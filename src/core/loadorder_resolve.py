"""Mapping a ``ddmanager.loadorder`` document onto the installed mods.

Each entry walks a ladder of candidate lists (exact save identity, workshop id, folder, unique
normalised title).  A rung with several free candidates does not stop the ladder: the set is
carried down and narrowed by the next rungs, so two local copies sharing one save identity are
told apart by the ``folder`` hint the document carries.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from src.core.findings import Finding
from src.core.identity_text import normalize_mod_identity
from src.core.ids import ModId, SaveIdentity, SaveSource, SourceKind
from src.core.load_order import LoadOrder
from src.core.loadorder_document import LoadOrderDocument, LoadOrderEntry
from src.core.model import ModInfo


@dataclass(frozen=True, slots=True)
class ResolveResult:
    """What :func:`resolve_document` found: the order to adopt and what could not be matched."""

    order: LoadOrder
    matched: tuple[tuple[int, ModId], ...]
    """``(document entry index, installed mod)`` pairs in document order."""
    unresolved: tuple[LoadOrderEntry, ...]
    findings: tuple[Finding, ...]


def _implied_kind(entry: LoadOrderEntry) -> SourceKind | None:
    source = entry.save_identity.source
    if source == SaveSource.STEAM:
        return SourceKind.WORKSHOP
    if source == SaveSource.LOCAL:
        return SourceKind.LOCAL
    return None


class _Index:
    """Lookup tables over the installed mods for the matching ladder."""

    def __init__(self, mods: Mapping[ModId, ModInfo]) -> None:
        self.mods = mods
        self.by_identity: dict[SaveIdentity, list[ModId]] = {}
        self.by_workshop: dict[str, list[ModId]] = {}
        self.by_title: dict[str, list[ModId]] = {}
        for mod, info in mods.items():
            self.by_identity.setdefault(info.save_identity, []).append(mod)
            if info.workshop_id:
                self.by_workshop.setdefault(info.workshop_id, []).append(mod)
            title = normalize_mod_identity(info.title)
            if title:
                self.by_title.setdefault(title, []).append(mod)

    def _folder(self, entry: LoadOrderEntry) -> list[ModId]:
        """The installed mod whose folder is ``entry.folder`` (or, without one, the identity
        name, which is the folder for local save names) when the kinds agree."""
        mod = ModId(entry.folder if entry.folder is not None else entry.save_identity.name)
        if mod not in self.mods:
            return []
        kind = _implied_kind(entry)
        return [mod] if kind is None or self.mods[mod].kind is kind else []

    def candidates(self, entry: LoadOrderEntry) -> list[list[ModId]]:
        """The ladder's candidate lists, strongest first."""
        title = normalize_mod_identity(entry.title)
        return [
            self.by_identity.get(entry.save_identity, []),
            self.by_workshop.get(entry.workshop_id or "", []) if entry.workshop_id else [],
            self._folder(entry),
            self.by_title.get(title, []) if title else [],
        ]


def _pick(candidates: list[list[ModId]], claimed: set[ModId]) -> tuple[ModId | None, bool]:
    """``(match, ambiguous)``: the unique unclaimed candidate the ladder narrows down to.

    The first rung with free candidates seeds the pool; every later rung that intersects the
    pool narrows it.  One candidate left is the match; a pool that never narrows to one is
    ``ambiguous``; no free candidate anywhere is neither.
    """
    pool: list[ModId] | None = None
    for rung in candidates:
        free = [mod for mod in rung if mod not in claimed]
        narrowed = free if pool is None else [mod for mod in free if mod in pool]
        if len(narrowed) == 1:
            return narrowed[0], False
        if narrowed:
            pool = narrowed
    return None, pool is not None


def _describe(entry: LoadOrderEntry) -> str:
    return entry.title or entry.folder or entry.save_identity.name


def resolve_document(
    doc: LoadOrderDocument, mods: Mapping[ModId, ModInfo], base: LoadOrder
) -> ResolveResult:
    """Map the document's entries onto installed mods and build the resulting order.

    Matching ladder per entry: exact save identity, then workshop id, then folder (only when
    the installed mod's kind agrees with the entry's source; the identity name stands in for
    a missing folder), then a unique normalised title.  Several free candidates on one rung
    are narrowed by the later rungs (see :func:`_pick`); an entry that stays ambiguous is
    left unresolved.  The result lists the matched mods in document order with the document's
    enabled flags, followed by every ``base`` entry not mentioned, disabled; nothing is ever
    pruned.
    """
    index = _Index(mods)
    claimed: set[ModId] = set()
    matched: list[tuple[int, ModId]] = []
    unresolved: list[LoadOrderEntry] = []
    findings: list[Finding] = []
    for position, entry in enumerate(doc.entries):
        pick, ambiguous = _pick(index.candidates(entry), claimed)
        if pick is not None:
            claimed.add(pick)
            matched.append((position, pick))
            continue
        label = _describe(entry)
        rule, what = (
            ("ambiguous", "Several installed mods match")
            if ambiguous
            else (
                "unresolved",
                "No installed mod matches",
            )
        )
        findings.append(Finding.warning(f"loadorder.{rule}", f"{what} {label!r}."))
        unresolved.append(entry)
    entries = [mod for _, mod in matched]
    enabled = frozenset(mod for position, mod in matched if doc.entries[position].enabled)
    entries.extend(mod for mod in base.entries if mod not in claimed)
    return ResolveResult(
        LoadOrder(tuple(entries), enabled), tuple(matched), tuple(unresolved), tuple(findings)
    )
