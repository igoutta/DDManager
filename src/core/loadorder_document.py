"""The ``ddmanager.loadorder`` v1 JSON document: types, dump, tolerant parse and building.

A document lists mods by their save identity (what the game writes into ``applied_ugcs_1_0``)
plus hints (folder, workshop id, title) that :mod:`src.core.loadorder_resolve` uses to map the
entries back onto the installed mods.  Parsing is total: every structural problem becomes a
:class:`~src.core.findings.Finding` instead of an exception.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from src.core.findings import Finding
from src.core.ids import ModId, SaveIdentity
from src.core.json_values import Extra, JsonObject, JsonValue, TypedFields
from src.core.load_order import LoadOrder, PriorityDirection, PrioritySetting
from src.core.model import ModInfo

FORMAT: Final = "ddmanager.loadorder"
FORMAT_VERSION: Final = 1
GAME: Final = "darkest_dungeon"
"""The ``game`` value written by this app (Steam app 262060)."""

_DOCUMENT_KEYS: Final[frozenset[str]] = frozenset({
    "format", "format_version", "name", "game", "priority_direction", "verified",
    "created_with", "created_at", "notes", "mods",
})  # fmt: skip
_ENTRY_KEYS: Final[frozenset[str]] = frozenset({
    "rank", "enabled", "title", "save_identity", "workshop_id", "folder", "tier",
})  # fmt: skip


@dataclass(frozen=True, slots=True)
class LoadOrderEntry:
    """One mod of a document; ``extra`` keeps unknown keys so a round trip loses nothing."""

    save_identity: SaveIdentity
    enabled: bool
    title: str
    folder: str | None
    workshop_id: str | None
    tier: str | None
    extra: Extra = ()


@dataclass(frozen=True, slots=True)
class LoadOrderDocument:
    """A parsed or built ``ddmanager.loadorder`` document."""

    name: str
    game: str
    priority: PrioritySetting
    created_with: str
    created_at: datetime | None
    notes: str
    entries: tuple[LoadOrderEntry, ...]
    extra: Extra = ()


def _error(rule: str, message: str) -> Finding:
    return Finding.error(f"loadorder.{rule}", message)


def _warning(rule: str, message: str) -> Finding:
    return Finding.warning(f"loadorder.{rule}", message)


# ---------------------------------------------------------------- dump


def _entry_json(entry: LoadOrderEntry, rank: int | None) -> JsonObject:
    obj: JsonObject = {}
    if rank is not None:
        obj["rank"] = rank
    obj.update(
        {
            "enabled": entry.enabled,
            "title": entry.title,
            "save_identity": {
                "name": entry.save_identity.name,
                "source": entry.save_identity.source,
            },
            "workshop_id": entry.workshop_id,
            "folder": entry.folder,
            "tier": entry.tier,
        }
    )
    obj.update(dict(entry.extra))
    return obj


def _entries_json(entries: Sequence[LoadOrderEntry]) -> list[JsonValue]:
    mods: list[JsonValue] = []
    rank = 0
    for entry in entries:
        if entry.enabled:
            rank += 1
        mods.append(_entry_json(entry, rank if entry.enabled else None))
    return mods


def dump_load_order(doc: LoadOrderDocument) -> str:
    """Serialise ``doc`` as pretty JSON (``indent=2``, ``ensure_ascii=False``, trailing newline).

    ``rank`` is written for enabled entries only (1-based over the enabled ones); unknown keys
    kept in ``extra`` follow the known ones at both levels.
    """
    obj: JsonObject = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "name": doc.name,
        "game": doc.game,
        "priority_direction": doc.priority.direction.value,
        "verified": doc.priority.verified,
        "created_with": doc.created_with,
        "created_at": doc.created_at.isoformat() if doc.created_at is not None else None,
        "notes": doc.notes,
        "mods": _entries_json(doc.entries),
    }
    obj.update(dict(doc.extra))
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------- parse


def _fields(obj: Mapping[str, object], where: str, findings: list[Finding]) -> TypedFields:
    """A :class:`TypedFields` whose type repairs become ``loadorder.bad_type`` warnings."""

    def report(key: str, expected: str) -> None:
        message = f"{where}: '{key}' should be {expected}; default used."
        findings.append(_warning("bad_type", message))

    return TypedFields(obj, report)


def _parse_priority(fields: TypedFields, findings: list[Finding]) -> PrioritySetting:
    raw = fields.str_("priority_direction", PriorityDirection.FIRST_WINS.value)
    try:
        direction = PriorityDirection(raw)
    except ValueError:
        findings.append(
            _warning("bad_priority", f"Unknown priority_direction {raw!r}; first_wins assumed.")
        )
        direction = PriorityDirection.FIRST_WINS
    return PrioritySetting(direction, fields.bool_("verified", default=True))


def _parse_created_at(fields: TypedFields, findings: list[Finding]) -> datetime | None:
    raw = fields.optional_str("created_at")
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        findings.append(_warning("bad_created_at", f"Unreadable created_at {raw!r}."))
        return None


def _parse_identity(obj: Mapping[str, object]) -> SaveIdentity | None:
    """``save_identity: {name, source}``; ``None`` (the entry is skipped) when unusable."""
    raw = obj.get("save_identity")
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    source = raw.get("source", "")
    if not isinstance(name, str) or not name or not isinstance(source, str):
        return None
    try:
        return SaveIdentity(name, source)
    except ValueError:
        return None


def _parse_entry(
    index: int, raw: object, findings: list[Finding]
) -> tuple[LoadOrderEntry | None, int | None]:
    """One ``mods[]`` item: the entry (or ``None`` when skipped) and its declared ``rank``."""
    where = f"mods[{index}]"
    if not isinstance(raw, dict):
        findings.append(_warning("bad_entry", f"{where} is not an object; skipped."))
        return None, None
    identity = _parse_identity(raw)
    if identity is None:
        findings.append(_error("missing_identity", f"{where} has no usable save_identity."))
        return None, None
    fields = _fields(raw, where, findings)
    rank = raw.get("rank")
    entry = LoadOrderEntry(
        save_identity=identity,
        enabled=fields.bool_("enabled", default=True),
        title=fields.str_("title"),
        folder=fields.optional_str("folder"),
        workshop_id=fields.optional_str("workshop_id"),
        tier=fields.optional_str("tier"),
        extra=fields.extra(_ENTRY_KEYS),
    )
    return entry, rank if isinstance(rank, int) and not isinstance(rank, bool) else None


def _check_rank(index: int, declared: int | None, actual: int, findings: list[Finding]) -> None:
    if declared is not None and declared != actual:
        findings.append(
            _warning(
                "rank_mismatch",
                f"mods[{index}] declares rank {declared} but sits at rank {actual}; "
                "the array order is used.",
            )
        )


def _parse_entries(raw: Sequence[object], findings: list[Finding]) -> tuple[LoadOrderEntry, ...]:
    """Entries in array order; a repeated ``(save_identity, folder)`` pair is skipped.

    The folder takes part in the key so a saved profile of two installed copies that share one
    save identity (what ``core.duplicate_identity`` reports) round-trips; two entries that
    cannot be told apart are a real duplicate and yield an ERROR finding.
    """
    entries: list[LoadOrderEntry] = []
    seen: set[tuple[SaveIdentity, str | None]] = set()
    rank = 0
    for index, item in enumerate(raw):
        entry, declared = _parse_entry(index, item, findings)
        if entry is None:
            continue
        key = (entry.save_identity, entry.folder)
        if key in seen:
            name = entry.save_identity.name
            findings.append(_error("duplicate_identity", f"mods[{index}] repeats {name!r}."))
            continue
        seen.add(key)
        if entry.enabled:
            rank += 1
            _check_rank(index, declared, rank, findings)
        entries.append(entry)
    return tuple(entries)


def _check_header(obj: Mapping[str, object]) -> tuple[list[object] | None, Finding | None]:
    """The structural checks that make the whole document unusable; else the ``mods`` list."""
    if obj.get("format") != FORMAT:
        return None, _error("wrong_format", f"Not a {FORMAT} file.")
    version = obj.get("format_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        return None, _error("bad_version", "The file has no valid format_version.")
    if version > FORMAT_VERSION:
        return None, _error("newer_version", "This file was made by a newer DD Manager.")
    mods = obj.get("mods")
    if not isinstance(mods, list):
        return None, _error("bad_mods", "The file has no 'mods' list.")
    return mods, None


def _load_json_object(text: str) -> tuple[Mapping[str, object] | None, Finding | None]:
    try:
        obj = json.loads(text)
    except ValueError as exc:
        return None, _error("invalid_json", f"The file is not valid JSON: {exc}")
    if not isinstance(obj, dict):
        return None, _error("wrong_format", "The file is not a JSON object.")
    return obj, None


def parse_load_order(text: str) -> tuple[LoadOrderDocument | None, list[Finding]]:
    """Parse a document; never raises.

    ``None`` plus an ERROR finding for invalid JSON, a wrong ``format``, a missing ``mods``
    list or a ``format_version`` newer than :data:`FORMAT_VERSION`.  Unknown keys are kept in
    ``extra``; a ``rank`` that disagrees with the array order yields a WARNING (the array
    wins); entries without a usable ``save_identity`` or repeating one (same identity and
    folder) are skipped with an ERROR finding.
    """
    findings: list[Finding] = []
    obj, problem = _load_json_object(text)
    if obj is None:
        return None, [problem] if problem else []
    mods, problem = _check_header(obj)
    if mods is None:
        return None, [problem] if problem else []
    fields = _fields(obj, "document", findings)
    doc = LoadOrderDocument(
        name=fields.str_("name"),
        game=fields.str_("game", GAME),
        priority=_parse_priority(fields, findings),
        created_with=fields.str_("created_with"),
        created_at=_parse_created_at(fields, findings),
        notes=fields.str_("notes"),
        entries=_parse_entries(mods, findings),
        extra=fields.extra(_DOCUMENT_KEYS),
    )
    return doc, findings


# ---------------------------------------------------------------- build from state


def document_from_order(
    order: LoadOrder,
    mods: Mapping[ModId, ModInfo],
    *,
    name: str,
    priority: PrioritySetting,
    created_with: str,
    created_at: datetime | None,
    tiers: Mapping[ModId, str],
    include_disabled: bool,
) -> LoadOrderDocument:
    """Build a document from the current order; entries without a ``ModInfo`` are left out.

    With ``include_disabled`` every ``order.entries`` slot is written (``enabled`` false for
    the inactive ones); otherwise only ``order.active()``.
    """
    ids = order.entries if include_disabled else order.active()
    entries = tuple(
        LoadOrderEntry(
            save_identity=mods[mod].save_identity,
            enabled=order.is_enabled(mod),
            title=mods[mod].title,
            folder=str(mod),
            workshop_id=mods[mod].workshop_id or None,
            tier=tiers.get(mod),
        )
        for mod in ids
        if mod in mods
    )
    return LoadOrderDocument(name, GAME, priority, created_with, created_at, "", entries)
