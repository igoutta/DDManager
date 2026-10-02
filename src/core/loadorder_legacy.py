"""Import of the legacy ``dd_mod_loadout.json`` (``legacy_loadout.py:30-46``) as a load-order
document, so the same :func:`src.core.loadorder_resolve.resolve_document` ladder maps it onto
the installed mods (by folder, since legacy loadouts only carried folder keys)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from src.core.findings import Finding
from src.core.ids import SaveIdentity
from src.core.json_values import Extra
from src.core.load_order import PrioritySetting
from src.core.loadorder_document import GAME, LoadOrderDocument, LoadOrderEntry

_EXTRA_KEYS: Final = ("nicknames", "categories", "category_memory")


@dataclass(frozen=True, slots=True)
class LegacyLoadoutExtras:
    """The non-order parts of a legacy loadout (``legacy_loadout.py:36-45``)."""

    nicknames: Mapping[str, str]
    categories: Mapping[str, str]
    category_memory: Mapping[str, str]


def _str_mapping(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {
        key: value for key, value in raw.items() if isinstance(key, str) and isinstance(value, str)
    }


def _entry(
    key: object, enabled: Mapping[object, object], findings: list[Finding]
) -> LoadOrderEntry | None:
    if not isinstance(key, str) or not key:
        findings.append(
            Finding.warning("loadorder.bad_entry", f"Ignoring a non-text order entry {key!r}.")
        )
        return None
    try:
        identity = SaveIdentity(key, "")
    except ValueError:
        findings.append(
            Finding.error(
                "loadorder.missing_identity", f"Folder name {key!r} cannot be a save identity."
            )
        )
        return None
    return LoadOrderEntry(
        save_identity=identity,
        enabled=bool(enabled.get(key, True)),
        title="",
        folder=key,
        workshop_id=None,
        tier=None,
    )


def _entries(
    order: Sequence[object], enabled: Mapping[object, object], findings: list[Finding]
) -> tuple[LoadOrderEntry, ...]:
    entries: list[LoadOrderEntry] = []
    seen: set[str] = set()
    for key in order:
        entry = _entry(key, enabled, findings)
        if entry is None:
            continue
        name = entry.save_identity.name
        if name in seen:
            findings.append(
                Finding.error("loadorder.duplicate_identity", f"Order repeats {name!r}.")
            )
            continue
        seen.add(name)
        entries.append(entry)
    return tuple(entries)


def parse_legacy_loadout(
    obj: object,
) -> tuple[LoadOrderDocument | None, LegacyLoadoutExtras | None, list[Finding]]:
    """Import a legacy ``dd_mod_loadout.json`` object (``legacy_loadout.py:30-46``).

    As the legacy loader (``84-89``) the object must carry ``order`` (a list) and ``enabled``
    (an object); otherwise ``(None, None, [ERROR])``.  Entries carry ``folder=key`` and the
    identity ``(key, "")`` so ``resolve_document`` matches them by folder; ``enabled``
    defaults to true per key (``legacy_loadout.py:33``).  ``mods_path`` is kept in ``extra``.
    """
    findings: list[Finding] = []
    order = obj.get("order") if isinstance(obj, dict) else None
    enabled = obj.get("enabled") if isinstance(obj, dict) else None
    if not isinstance(obj, dict) or not isinstance(order, list) or not isinstance(enabled, dict):
        problem = Finding.error(
            "loadorder.wrong_format", "That file does not look like a valid loadout."
        )
        return None, None, [problem]
    mods_path = obj.get("mods_path")
    extra: Extra = (("mods_path", mods_path),) if isinstance(mods_path, str) else ()
    doc = LoadOrderDocument(
        name="",
        game=GAME,
        priority=PrioritySetting(),
        created_with="legacy",
        created_at=None,
        notes="",
        entries=_entries(order, enabled, findings),
        extra=extra,
    )
    nicknames, categories, memory = (_str_mapping(obj.get(key)) for key in _EXTRA_KEYS)
    return doc, LegacyLoadoutExtras(nicknames, categories, memory), findings
