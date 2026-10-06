"""The ``mod_state.json`` document as the new app reads and writes it.

The 22 legacy keys (``state.py:8-32``, see :mod:`src.core.state_migrate`) stay the on-disk
format; ``schema_version`` is added on write.  :func:`parse_state` sanitises
(:mod:`src.core.state_sanitize`, reporting every repair as a ``state.*`` finding), migrates and
exposes typed views in a :class:`StateDoc`.  :func:`render_state` applies a :class:`StateChanges`
delta onto the untouched original document so unknown keys and the original key order survive a
round trip.
"""

import copy
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, cast

from src.core.categories import DEFAULT_CATEGORIES
from src.core.findings import Finding
from src.core.ids import ModId, SaveIdentity
from src.core.json_values import JsonValue
from src.core.load_order import LoadOrder
from src.core.state_migrate import (
    LEGACY_KEYS,
    SCHEMA_VERSION,
    TEXT_KEYS,
    VIEW_MODES,
    StateDict,
    build_default_state,
    legacy_migrate,
    mod_metadata_is_complete,
)
from src.core.state_sanitize import sanitize_state

__all__ = [
    "LEGACY_KEYS",
    "SCHEMA_VERSION",
    "VIEW_MODES",
    "StateChanges",
    "StateDoc",
    "StateSettings",
    "build_default_state",
    "legacy_migrate",
    "mod_metadata_is_complete",
    "parse_state",
    "render_state",
    "render_state_json",
]

_SETTING_KEYS: Final[frozenset[str]] = frozenset((*TEXT_KEYS, "first_run_summary_shown"))


# ---------------------------------------------------------------- parsed document


@dataclass(frozen=True, slots=True)
class StateSettings:
    """The scalar settings of ``mod_state.json``."""

    language: str
    mods_path: str
    last_save_path: str
    last_backup_path: str
    last_output_path: str
    selected_profile_path: str
    manual_game_root: str
    manual_local_mods_path: str
    manual_workshop_mods_path: str
    first_run_summary_shown: bool
    view_mode: str


@dataclass(frozen=True, slots=True)
class StateDoc:
    """A parsed ``mod_state.json``: typed views plus the migrated document they came from."""

    raw: Mapping[str, JsonValue]
    order: LoadOrder
    categories: Mapping[ModId, str]
    nicknames: Mapping[ModId, str]
    category_order: tuple[str, ...]
    custom_categories: tuple[str, ...]
    category_colors: Mapping[str, str]
    category_memory: Mapping[str, str]
    auto_category_attempted: frozenset[ModId]
    metadata_identities: Mapping[ModId, SaveIdentity]
    settings: StateSettings


def _str_items(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _str_mapping(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(value, str)}


def _mod_mapping(raw: object) -> dict[ModId, str]:
    return {ModId(key): value for key, value in _str_mapping(raw).items() if value}


def _attempted(raw: object) -> frozenset[ModId]:
    if not isinstance(raw, dict):
        return frozenset()
    return frozenset(ModId(key) for key, value in raw.items() if value)


def _metadata_identities(raw: object, findings: list[Finding]) -> dict[ModId, SaveIdentity]:
    """``save_name``/``save_source`` of every complete metadata entry (``dd2.py:557-573``)."""
    identities: dict[ModId, SaveIdentity] = {}
    if not isinstance(raw, dict):
        return identities
    for mod, entry in raw.items():
        if not mod_metadata_is_complete(entry) or not isinstance(entry, dict):
            continue
        name, source = entry.get("save_name"), entry.get("save_source")
        if not isinstance(name, str) or not isinstance(source, str):
            continue
        try:
            identities[ModId(mod)] = SaveIdentity(name, source)
        except ValueError:
            message = f"Metadata of {mod!r} has an unusable identity."
            findings.append(Finding.warning("state.bad_metadata", message))
    return identities


def _load_order(state: StateDict) -> LoadOrder:
    """``entries`` = ``order``; enabled = every entry whose flag is not falsy (``dd2.py:1754``)."""
    entries = tuple(ModId(item) for item in _str_items(state["order"]))
    raw_flags = state["enabled"]
    flags = raw_flags if isinstance(raw_flags, dict) else {}
    return LoadOrder(entries, frozenset(mod for mod in entries if bool(flags.get(mod, True))))


def _settings(state: StateDict) -> StateSettings:
    def text(key: str) -> str:
        return str(state[key])

    return StateSettings(
        language=text("language"),
        mods_path=text("mods_path"),
        last_save_path=text("last_save_path"),
        last_backup_path=text("last_backup_path"),
        last_output_path=text("last_output_path"),
        selected_profile_path=text("selected_profile_path"),
        manual_game_root=text("manual_game_root"),
        manual_local_mods_path=text("manual_local_mods_path"),
        manual_workshop_mods_path=text("manual_workshop_mods_path"),
        first_run_summary_shown=bool(state["first_run_summary_shown"]),
        view_mode=text("view_mode"),
    )


def parse_state(obj: object, *, default_language: str = "en") -> tuple[StateDoc, list[Finding]]:
    """Tolerant reader: sanitise (reporting ``state.*`` WARNING findings), then migrate.

    Where ``state.py:35-76`` would crash (a non-object root, nulls or wrongly typed values)
    the default is used instead; invalid or duplicate ``order`` entries are dropped.
    """
    findings: list[Finding] = []
    migrated = legacy_migrate(sanitize_state(obj, findings), default_language, DEFAULT_CATEGORIES)
    state: StateDict = dict(migrated)
    doc = StateDoc(
        raw=copy.deepcopy(migrated),
        order=_load_order(state),
        categories=_mod_mapping(state["categories"]),
        nicknames=_mod_mapping(state["nicknames"]),
        category_order=tuple(_str_items(state["category_order"])),
        custom_categories=tuple(_str_items(state["custom_categories"])),
        category_colors=_str_mapping(state["category_colors"]),
        category_memory=_str_mapping(state["category_memory"]),
        auto_category_attempted=_attempted(state["auto_category_attempted"]),
        metadata_identities=_metadata_identities(state["metadata"], findings),
        settings=_settings(state),
    )
    return doc, findings


# ---------------------------------------------------------------- render


@dataclass(frozen=True, slots=True)
class StateChanges:
    """A delta to apply on a :class:`StateDoc`; ``None`` fields are left untouched.

    ``categories``/``nicknames`` values of ``None`` unassign; ``category_memory_updates`` and
    ``attempted`` merge (``unattempted`` drops ids again, after a folder rename);
    ``category_colors``, ``category_order``, ``custom_categories``, ``category_memory`` and
    ``mod_paths`` replace wholesale (``dd2.py:6020``, and the category editor's purge of removed
    categories); ``settings`` names scalar keys.
    """

    order: LoadOrder | None = None
    categories: Mapping[ModId, str | None] | None = None
    nicknames: Mapping[ModId, str | None] | None = None
    category_order: Sequence[str] | None = None
    custom_categories: Sequence[str] | None = None
    category_colors: Mapping[str, str] | None = None
    category_memory_updates: Mapping[str, str] | None = None
    attempted: Iterable[ModId] | None = None
    mod_paths: Mapping[ModId, str] | None = None
    settings: Mapping[str, JsonValue] | None = None
    category_memory: Mapping[str, str] | None = None
    unattempted: Iterable[ModId] | None = None


def _dict_at(doc: StateDict, key: str) -> dict[str, object]:
    value = doc.get(key)
    if not isinstance(value, dict):
        value = {}
        doc[key] = value
    return value


def _apply_assignments(doc: StateDict, key: str, updates: Mapping[ModId, str | None]) -> None:
    target = _dict_at(doc, key)
    for mod, value in updates.items():
        if value is None:
            target.pop(mod, None)
        else:
            target[mod] = value


def _apply_order(doc: StateDict, order: LoadOrder) -> None:
    """Write ``order`` and an explicit bool per entry in ``enabled``.

    Keys of mods that are no longer entries (a renamed folder, a forgotten missing mod) are
    dropped: every reader defaults an absent key, so they would only ever go stale.
    """
    doc["order"] = list(order.entries)
    flags = _dict_at(doc, "enabled")
    entries = set(order.entries)
    for stale in [key for key in flags if key not in entries]:
        del flags[stale]
    for mod in order.entries:
        flags[mod] = order.is_enabled(mod)


def _apply_settings(doc: StateDict, settings: Mapping[str, JsonValue]) -> None:
    unknown = set(settings) - _SETTING_KEYS
    if unknown:
        raise ValueError(f"not settings keys: {', '.join(sorted(unknown))}")
    doc.update(settings)


def _apply_replacements(doc: StateDict, changes: StateChanges) -> None:
    if changes.category_order is not None:
        doc["category_order"] = list(changes.category_order)
    if changes.custom_categories is not None:
        doc["custom_categories"] = list(changes.custom_categories)
    if changes.category_colors is not None:
        doc["category_colors"] = dict(changes.category_colors)
    if changes.category_memory is not None:
        doc["category_memory"] = dict(changes.category_memory)
    if changes.mod_paths is not None:
        doc["mod_paths"] = {str(mod): path for mod, path in changes.mod_paths.items()}


def _apply_merges(doc: StateDict, changes: StateChanges) -> None:
    if changes.categories is not None:
        _apply_assignments(doc, "categories", changes.categories)
    if changes.nicknames is not None:
        _apply_assignments(doc, "nicknames", changes.nicknames)
    if changes.category_memory_updates is not None:
        _dict_at(doc, "category_memory").update(changes.category_memory_updates)
    _apply_attempted(doc, changes)


def _apply_attempted(doc: StateDict, changes: StateChanges) -> None:
    """Mark ``attempted`` ids, then drop ``unattempted`` ones."""
    if changes.attempted is None and changes.unattempted is None:
        return
    attempted = _dict_at(doc, "auto_category_attempted")
    for mod in changes.attempted or ():
        attempted[mod] = True
    for mod in changes.unattempted or ():
        attempted.pop(mod, None)


def render_state(base: StateDoc, changes: StateChanges) -> dict[str, JsonValue]:
    """The document to write: ``base.raw`` plus ``changes``, ``schema_version`` appended.

    ``metadata`` is never touched; ``enabled`` always carries an explicit bool for every
    ``order`` entry; the original key order is preserved and new keys are appended.
    """
    doc: StateDict = copy.deepcopy(dict(base.raw))
    _apply_order(doc, changes.order if changes.order is not None else base.order)
    _apply_replacements(doc, changes)
    _apply_merges(doc, changes)
    if changes.settings is not None:
        _apply_settings(doc, changes.settings)
    doc["schema_version"] = SCHEMA_VERSION
    return cast("dict[str, JsonValue]", doc)


def render_state_json(doc: Mapping[str, object]) -> str:
    """``json.dumps(indent=2)`` with the default ``ensure_ascii`` and no trailing newline
    (the byte style of ``state.py:123``)."""
    return json.dumps(doc, indent=2)
