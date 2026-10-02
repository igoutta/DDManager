"""The tolerant half of reading ``mod_state.json``: repair what ``legacy_migrate`` would crash on.

Every repair is reported as a ``state.*`` WARNING finding.  A repaired key is DELETED so the
migration fills in its default (and appends it in default order, as a missing key would be).
"""

import copy
from typing import Final

from src.core.findings import Finding
from src.core.ids import parse_mod_id
from src.core.state_migrate import (
    DICT_KEYS,
    LIST_KEYS,
    TEXT_KEYS,
    TEXT_LIST_KEYS,
    TEXT_VALUE_DICT_KEYS,
    VIEW_MODES,
    StateDict,
)

type _TypeRule = tuple[str, type | tuple[type, ...], str]
"""``(key, expected type(s), human label)``."""

_TYPE_RULES: Final[tuple[_TypeRule, ...]] = (
    *((key, str, "text") for key in TEXT_KEYS),
    ("first_run_summary_shown", bool, "true/false"),
    *((key, list, "a list") for key in LIST_KEYS),
    *((key, dict, "an object") for key in DICT_KEYS),
)


def _warn(rule: str, message: str) -> Finding:
    return Finding.warning(f"state.{rule}", message)


def _drop_wrong_types(state: StateDict, findings: list[Finding]) -> None:
    """Delete every present key whose value has the wrong type (the default is filled later)."""
    for key, expected, label in _TYPE_RULES:
        if key in state and not isinstance(state[key], expected):
            findings.append(_warn("bad_type", f"'{key}' should be {label}; default used."))
            del state[key]
    view_mode = state.get("view_mode")
    if isinstance(view_mode, str) and view_mode not in VIEW_MODES:
        findings.append(_warn("bad_view_mode", f"Unknown view mode {view_mode!r}."))
        del state["view_mode"]


def _drop_non_text_items(state: StateDict, findings: list[Finding]) -> None:
    """Text lists lose non-text items; text-valued dicts lose entries with non-text values."""
    for key in TEXT_LIST_KEYS:
        raw = state.get(key)
        if isinstance(raw, list):
            kept = [item for item in raw if isinstance(item, str)]
            if len(kept) != len(raw):
                findings.append(_warn("bad_entry", f"'{key}' had non-text entries; dropped."))
                state[key] = kept
    for key in TEXT_VALUE_DICT_KEYS:
        raw = state.get(key)
        if isinstance(raw, dict):
            kept = {mod: value for mod, value in raw.items() if isinstance(value, str)}
            if len(kept) != len(raw):
                findings.append(_warn("bad_entry", f"'{key}' had non-text values; dropped."))
                state[key] = kept


def _valid_mod_id(item: object) -> str | None:
    if not isinstance(item, str):
        return None
    try:
        return parse_mod_id(item)
    except ValueError:
        return None


def _drop_bad_order_entries(state: StateDict, findings: list[Finding]) -> None:
    """Keep only valid, unique mod ids in ``order`` (``src.core.ids.parse_mod_id``)."""
    raw = state.get("order")
    if not isinstance(raw, list):
        return
    kept: list[str] = []
    seen: set[str] = set()
    for item in raw:
        mod = _valid_mod_id(item)
        if mod is None:
            findings.append(_warn("bad_order_entry", f"Ignoring invalid order entry {item!r}."))
        elif mod in seen:
            findings.append(_warn("duplicate_order_entry", f"Order repeats {mod!r}."))
        else:
            seen.add(mod)
            kept.append(mod)
    state["order"] = kept


def sanitize_state(obj: object, findings: list[Finding]) -> StateDict:
    """A deep copy of ``obj`` that ``legacy_migrate`` accepts; repairs are appended to ``findings``.

    A non-object root yields an empty document (every key defaults).
    """
    if not isinstance(obj, dict):
        findings.append(_warn("not_object", "The state file is not a JSON object; defaults used."))
        return {}
    state: StateDict = copy.deepcopy(obj)
    _drop_wrong_types(state, findings)
    _drop_non_text_items(state, findings)
    _drop_bad_order_entries(state, findings)
    return state
