"""The ``mod_state.json`` schema (``state.py:8-32``) and its verbatim legacy migration.

:func:`legacy_migrate` ports ``state.py:35-76`` including its failure modes: badly typed
values raise (``TypeError`` here where the legacy raised ``AttributeError``/``TypeError``), so
:func:`src.core.legacy_state.parse_state` sanitises first.  The key tables describe the schema
for the sanitizer and the renderer.
"""

import copy
from collections.abc import Iterable, Mapping, Sequence
from typing import Final, cast

from src.core.categories import dedupe_category_names, normalize_hex_color
from src.core.json_values import JsonValue

LEGACY_KEYS: Final[tuple[str, ...]] = (
    "language",
    "mods_path",
    "last_save_path",
    "last_backup_path",
    "last_output_path",
    "selected_profile_path",
    "manual_game_root",
    "manual_local_mods_path",
    "manual_workshop_mods_path",
    "first_run_summary_shown",
    "view_mode",
    "order",
    "categories",
    "category_order",
    "category_colors",
    "category_memory",
    "auto_category_attempted",
    "custom_categories",
    "enabled",
    "nicknames",
    "metadata",
    "mod_paths",
)
SCHEMA_VERSION: Final = 1
VIEW_MODES: Final = ("No Icons", "Compact", "Comfortable", "Visual")

TEXT_KEYS: Final = (
    "language",
    "mods_path",
    "last_save_path",
    "last_backup_path",
    "last_output_path",
    "selected_profile_path",
    "manual_game_root",
    "manual_local_mods_path",
    "manual_workshop_mods_path",
    "view_mode",
)
"""Scalar settings that are text."""
LIST_KEYS: Final = ("order", "category_order", "custom_categories")
DICT_KEYS: Final = (
    "categories",
    "category_colors",
    "category_memory",
    "auto_category_attempted",
    "enabled",
    "nicknames",
    "metadata",
    "mod_paths",
)
TEXT_LIST_KEYS: Final = ("category_order", "custom_categories")
"""Lists whose items are text."""
TEXT_VALUE_DICT_KEYS: Final = (
    "categories",
    "category_colors",
    "category_memory",
    "nicknames",
    "mod_paths",
)
"""Dicts whose values are text."""
_METADATA_REQUIRED_KEYS: Final = (
    "title",
    "published_file_id",
    "save_name",
    "save_source",
    "version_label",
    "updated_label",
    "black_reliquary",
    "metadata_path",
    "project_mtime",
    "localization_signature",
    "workshop_timeupdated",
)

type StateDict = dict[str, object]
"""The working document: values are narrowed with ``isinstance`` where they are read."""


def build_default_state(
    default_language: str, default_categories: Sequence[str]
) -> dict[str, JsonValue]:
    """Verbatim ``state.py:8-32``."""
    return {
        "language": default_language,
        "mods_path": "",
        "last_save_path": "",
        "last_backup_path": "",
        "last_output_path": "",
        "selected_profile_path": "",
        "manual_game_root": "",
        "manual_local_mods_path": "",
        "manual_workshop_mods_path": "",
        "first_run_summary_shown": False,
        "view_mode": "Comfortable",
        "order": [],
        "categories": {},
        "category_order": list(default_categories),
        "category_colors": {},
        "category_memory": {},
        "auto_category_attempted": {},
        "custom_categories": [],
        "enabled": {},
        "nicknames": {},
        "metadata": {},
        "mod_paths": {},
    }


# ---------------------------------------------------------------- typed access


def _expect_dict(state: StateDict, key: str) -> dict[str, object]:
    value = state[key]
    if not isinstance(value, dict):
        raise TypeError(f"'{key}' must be an object, not {type(value).__name__}")
    return value


def _expect_list(state: StateDict, key: str) -> list[object]:
    value = state[key]
    if not isinstance(value, list):
        raise TypeError(f"'{key}' must be a list, not {type(value).__name__}")
    return value


def _expect_text(key: str, item: object) -> str:
    """The legacy called ``.lower()`` on every name it kept; anything else crashed."""
    if isinstance(item, str):
        return item
    raise TypeError(f"'{key}' entries must be text, not {type(item).__name__}")


def _truthy_names(key: str, items: Iterable[object]) -> list[str]:
    """``if cat and cat.lower()`` (``state.py:49, 58, 70, 73``): falsy skipped, non-text raises."""
    return [_expect_text(key, item) for item in items if item]


def _all_names(key: str, items: Iterable[object]) -> list[str]:
    """``cat.lower() for cat in ...`` (``state.py:56``): every item must be text."""
    return [_expect_text(key, item) for item in items]


# ---------------------------------------------------------------- migration


def _normalized_colors(colors: Mapping[str, object]) -> dict[str, str]:
    """``state.py:41-45``: keep the colours ``normalize_hex_color`` accepts, normalised."""
    result: dict[str, str] = {}
    for cat, color in colors.items():
        normalized = normalize_hex_color(str(color)) if color else None
        if normalized:
            result[cat] = normalized
    return result


def _append_unknown_customs(
    custom: list[str], assigned: Iterable[str], default_categories: Sequence[str]
) -> None:
    """``state.py:55-60``: assigned categories unknown to defaults/customs become customs."""
    existing = {cat.lower() for cat in default_categories}
    existing.update(cat.lower() for cat in custom)
    for cat in dedupe_category_names(assigned):
        if cat.lower() not in existing:
            custom.append(cat)
            existing.add(cat.lower())


def _complete_category_order(
    order: list[str],
    default_categories: Sequence[str],
    custom: Sequence[str],
    assigned: Iterable[str],
) -> None:
    """``state.py:62-74``: append defaults, customs and assigned names missing from the order.

    The guards differ per group exactly as in the legacy: none for defaults, ``if cat`` for
    customs, ``if cat`` and not a pseudo category for assigned names.
    """
    seen = {cat.lower() for cat in order}
    for cat in (*default_categories, *(c for c in custom if c), *dedupe_category_names(assigned)):
        if cat.lower() not in seen:
            order.append(cat)
            seen.add(cat.lower())


def legacy_migrate(
    state: Mapping[str, object] | None, default_language: str, default_categories: Sequence[str]
) -> dict[str, JsonValue]:
    """Verbatim ``state.py:35-76`` (``migrate_state_data``) over a deep copy of ``state``.

    Missing keys get defaults, colours are normalised (``dd2.py:623-631``), ``category_order``
    is deduplicated and completed with defaults, custom and assigned categories.  Badly typed
    values raise exactly like the legacy (``TypeError``): containers of the wrong type, and
    non-text category names that the legacy would have called ``.lower()`` on (every
    ``custom_categories`` item, every truthy ``category_order`` item or assigned category).
    :func:`src.core.legacy_state.parse_state` is the tolerant entry point.
    """
    result: StateDict = copy.deepcopy(dict(state or {}))
    for key, value in build_default_state(default_language, default_categories).items():
        result.setdefault(key, value)
    result["category_colors"] = _normalized_colors(_expect_dict(result, "category_colors"))
    order_names = _truthy_names("category_order", _expect_list(result, "category_order"))
    ordered = list(dedupe_category_names(order_names))
    result["category_order"] = ordered
    custom = _expect_list(result, "custom_categories")
    assigned = _truthy_names("categories", _expect_dict(result, "categories").values())
    customs = _all_names("custom_categories", custom)
    _append_unknown_customs(customs, assigned, default_categories)
    custom.extend(customs[len(custom) :])
    _complete_category_order(ordered, default_categories, customs, assigned)
    return cast("dict[str, JsonValue]", result)


def mod_metadata_is_complete(metadata: object) -> bool:
    """Verbatim ``dd2.py:557-573``: a dict carrying every cached metadata key."""
    if not isinstance(metadata, dict):
        return False
    return all(key in metadata for key in _METADATA_REQUIRED_KEYS)
