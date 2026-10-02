"""The legacy category system, pure: constants, lookups and the category-editor operations.

Ports ``categories.py:7-100`` (data and helpers), ``dd2.py:623-631`` (``normalize_hex_color``)
and ``categories.py:292-384`` (editor operations) with explicit arguments instead of the
legacy ``state`` dict and with functional (copying) list operations.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from src.core.ids import ModId

_HEX_COLOR_RE = re.compile(r"#?[0-9A-Fa-f]{6}")

DEFAULT_CATEGORIES: Final[tuple[str, ...]] = (
    "UI",
    "Districts",
    "Dungeons",
    "Quirks",
    "Trinkets",
    "Enemies",
    "Class Patch",
    "Class",
    "Skins",
)
"""``categories.py:32-42``."""

CATEGORY_COLORS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "UI": "#8FA6B8",
        "Districts": "#6D9C9A",
        "Dungeons": "#B88B4A",
        "Quirks": "#B26B7B",
        "Trinkets": "#C1A85D",
        "Enemies": "#B65A4D",
        "Class Patch": "#879B5B",
        "Class": "#A4B56C",
        "Skins": "#9D7A9A",
        "Unassigned": "#82786B",
    }
)
"""``categories.py:7-18``."""

CATEGORY_COLOR_CYCLE: Final[tuple[str, ...]] = (
    "#5F8B7E",
    "#A66A4A",
    "#7D8FB3",
    "#A46D8A",
    "#9F9153",
    "#5E7A52",
    "#B46A5B",
    "#6E8C9C",
)
"""``categories.py:20-29``."""

PSEUDO_CATEGORIES: Final[tuple[str, ...]] = ("All", "Unassigned")
"""Filter labels that are never real categories."""


def normalize_hex_color(value: str) -> str | None:
    """``dd2.py:623-631``: ``#RRGGBB`` upper-cased, or ``None`` when the text is not one."""
    if not value:
        return None
    text = str(value).strip()
    if not _HEX_COLOR_RE.fullmatch(text):
        return None
    return f"#{text.removeprefix('#').upper()}"


def dedupe_category_names(*groups: Iterable[str]) -> tuple[str, ...]:
    """``categories.py:49-63`` / ``state.py:47-53``: the names of ``groups`` in order, without
    blanks, pseudo categories or case-insensitive (``str.lower``, like the legacy) repeats."""
    categories: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for cat in group:
            if cat and cat not in PSEUDO_CATEGORIES and cat.lower() not in seen:
                categories.append(cat)
                seen.add(cat.lower())
    return tuple(categories)


def get_categories(
    category_order: Sequence[str], custom_categories: Sequence[str], assigned: Iterable[str]
) -> tuple[str, ...]:
    """``categories.py:44-65``: ordered, then custom, then discovered names without duplicates."""
    return dedupe_category_names(category_order, custom_categories, assigned)


def get_category_priority(
    categories: Sequence[str], base: Mapping[str, int], fallback: int = 700
) -> dict[str, int]:
    """``categories.py:67-79`` over an already-combined category list (see ``get_categories``)."""
    priority = {cat: index * 100 for index, cat in enumerate(categories)}
    for cat, value in base.items():
        priority.setdefault(cat, value)
    priority.setdefault("Unassigned", fallback)
    return priority


def category_color(category: str, colors: Mapping[str, str], fallback: str) -> str:
    """``categories.py:82-87``: user colour (normalised), then built-in, then ``fallback``."""
    custom = normalize_hex_color(colors.get(category, ""))
    if custom:
        return custom
    return CATEGORY_COLORS.get(category, fallback)


def default_color_for_new_category(colors: Mapping[str, str], fallback: str) -> str:
    """``categories.py:91-100``: the first cycle colour no user colour already uses."""
    used = {normalized for color in colors.values() if (normalized := normalize_hex_color(color))}
    for color in CATEGORY_COLOR_CYCLE:
        normalized = normalize_hex_color(color)
        if normalized and normalized not in used:
            return normalized
    return normalize_hex_color(CATEGORY_COLOR_CYCLE[0]) or fallback


def move_category(categories: Sequence[str], index: int, delta: int) -> tuple[str, ...]:
    """``categories.py:292-300`` as a copy: swap ``index`` with ``index + delta`` if both exist."""
    items = list(categories)
    new_index = index + delta
    if not (0 <= index < len(items)) or not (0 <= new_index < len(items)):
        return tuple(items)
    items[index], items[new_index] = items[new_index], items[index]
    return tuple(items)


def move_category_to_index(categories: Sequence[str], index: int, target: int) -> tuple[str, ...]:
    """``categories.py:303-314`` as a copy: pop ``index`` and insert it at ``target``."""
    items = list(categories)
    if not (0 <= index < len(items)) or not (0 <= target < len(items)) or index == target:
        return tuple(items)
    items.insert(target, items.pop(index))
    return tuple(items)


@dataclass(frozen=True, slots=True)
class CategoryEditorState:
    """The category editor's working copy (the five lists the legacy dialog mutated in place)."""

    categories: tuple[str, ...]
    custom_categories: tuple[str, ...]
    category_colors: Mapping[str, str]
    renamed: Mapping[str, str]
    """``new name -> original name`` bookkeeping (``categories.py:329-331``)."""
    removed: tuple[str, ...]
    """Custom categories removed in this session, in removal order."""


def add_custom_category(
    state: CategoryEditorState, name: str, chosen_color: str
) -> CategoryEditorState:
    """``categories.py:317-322``: append ``name`` as a custom category with ``chosen_color``."""
    return CategoryEditorState(
        categories=(*state.categories, name),
        custom_categories=(*state.custom_categories, name),
        category_colors={**state.category_colors, name: chosen_color},
        renamed=state.renamed,
        removed=state.removed,
    )


def rename_custom_category(
    state: CategoryEditorState, index: int, old_name: str, new_name: str
) -> CategoryEditorState:
    """``categories.py:325-332``: rename the custom category at ``index`` (bookkeeping kept).

    Raises ``ValueError`` when ``old_name`` is not a custom category (the legacy ``KeyError``).
    """
    if old_name not in state.custom_categories:
        raise ValueError(f"{old_name!r} is not a custom category")
    categories = list(state.categories)
    categories[index] = new_name
    custom = (*(name for name in state.custom_categories if name != old_name), new_name)
    colors = dict(state.category_colors)
    if old_name in colors:
        colors[new_name] = colors.pop(old_name)
    renamed = dict(state.renamed)
    original_name = renamed.pop(old_name, old_name)
    renamed[new_name] = original_name
    return CategoryEditorState(
        categories=tuple(categories),
        custom_categories=custom,
        category_colors=colors,
        renamed=renamed,
        removed=state.removed,
    )


def remove_custom_category(
    state: CategoryEditorState, index: int, category_name: str
) -> CategoryEditorState:
    """``categories.py:335-342``: drop the custom category at ``index`` and record the removal.

    Raises ``ValueError`` when ``category_name`` is not a custom category (the legacy
    ``KeyError``).
    """
    if category_name not in state.custom_categories:
        raise ValueError(f"{category_name!r} is not a custom category")
    categories = list(state.categories)
    del categories[index]
    colors = {name: color for name, color in state.category_colors.items() if name != category_name}
    return CategoryEditorState(
        categories=tuple(categories),
        custom_categories=tuple(name for name in state.custom_categories if name != category_name),
        category_colors=colors,
        renamed=state.renamed,
        removed=(*state.removed, category_name),
    )


@dataclass(frozen=True, slots=True)
class CategoryChanges:
    """What applying the editor produces (``categories.py:344-384``)."""

    category_order: tuple[str, ...]
    custom_categories: tuple[str, ...]
    category_colors: dict[str, str]
    assignments: dict[ModId, str | None]
    """Only the mods whose category changed: the new name, or ``None`` to unassign."""
    category_memory: dict[str, str]
    """The complete resulting memory (renamed values applied, removed categories purged)."""


def _renamed_pairs(renamed: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    """``categories.py:349-353``: ``(old, new)`` for every effective rename."""
    return tuple((old, new) for new, old in renamed.items() if old != new)


def _effective_removals(state: CategoryEditorState) -> tuple[str, ...]:
    """Removed customs that were not re-added and are not the original name of a rename."""
    return tuple(
        name
        for name in dict.fromkeys(state.removed)
        if name not in state.custom_categories and name not in state.renamed.values()
    )


def _final_colors(state: CategoryEditorState) -> dict[str, str]:
    """``categories.py:378-382``: normalised colours for the surviving categories only."""
    colors: dict[str, str] = {}
    for cat in state.categories:
        normalized = normalize_hex_color(state.category_colors.get(cat, ""))
        if normalized:
            colors[cat] = normalized
    return colors


def apply_category_editor_changes(
    state: CategoryEditorState,
    *,
    assignments: Mapping[ModId, str],
    category_memory: Mapping[str, str],
) -> CategoryChanges:
    """``categories.py:344-384``: renames propagate, removed customs unassign and purge memory."""
    final_categories = tuple(state.categories)
    final_custom = tuple(cat for cat in final_categories if cat not in DEFAULT_CATEGORIES)
    rename_map = dict(_renamed_pairs(state.renamed))
    removed = set(_effective_removals(state))

    assignment_changes: dict[ModId, str | None] = {}
    for mod, category in assignments.items():
        renamed_to = rename_map.get(category, category)
        if renamed_to in removed:
            assignment_changes[mod] = None
        elif renamed_to != category:
            assignment_changes[mod] = renamed_to

    memory: dict[str, str] = {}
    for key, category in category_memory.items():
        renamed_to = rename_map.get(category, category)
        if renamed_to not in removed:
            memory[key] = renamed_to

    return CategoryChanges(
        category_order=final_categories,
        custom_categories=final_custom,
        category_colors=_final_colors(state),
        assignments=assignment_changes,
        category_memory=memory,
    )
