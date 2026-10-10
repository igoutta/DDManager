"""The category system with explicit arguments (src/core/categories.py).

Contract: ``get_categories``, ``get_category_priority``, ``category_color``,
``default_color_for_new_category`` and ``normalize_hex_color`` take their inputs explicitly
instead of a state dict; the editor operations are functional over ``CategoryEditorState`` and
``apply_category_editor_changes`` returns a ``CategoryChanges`` instead of mutating.

Call shapes:
``add_custom_category(state, name, color)``, ``rename_custom_category(state, index, old, new)``,
``remove_custom_category(state, index, name)``; ``CategoryEditorState.renamed`` maps new name ->
original name; ``removed`` lists the customs removed
through ``remove_custom_category`` so ``apply_category_editor_changes`` can unassign them.
"""

import dataclasses
from collections.abc import Mapping, Sequence

import pytest

from src.core.categories import (
    CATEGORY_COLOR_CYCLE,
    CATEGORY_COLORS,
    DEFAULT_CATEGORIES,
    PSEUDO_CATEGORIES,
    CategoryChanges,
    CategoryEditorState,
    add_custom_category,
    apply_category_editor_changes,
    category_color,
    dedupe_category_names,
    default_color_for_new_category,
    get_categories,
    get_category_priority,
    move_category,
    move_category_to_index,
    normalize_hex_color,
    remove_custom_category,
    rename_custom_category,
)
from src.core.ids import ModId

FALLBACK = "#F2E9DC"
BASE_PRIORITY = {
    "UI": 0,
    "Districts": 100,
    "Dungeons": 200,
    "Quirks": 250,
    "Trinkets": 300,
    "Enemies": 400,
    "Class Patch": 450,
    "Class": 500,
    "Skins": 600,
    "Unassigned": 700,
}


# ----------------------------------------------------------------- constants


def test_constants_are_the_expected_values() -> None:
    assert DEFAULT_CATEGORIES == (
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
    assert CATEGORY_COLORS == {
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
    assert CATEGORY_COLOR_CYCLE == (
        "#5F8B7E",
        "#A66A4A",
        "#7D8FB3",
        "#A46D8A",
        "#9F9153",
        "#5E7A52",
        "#B46A5B",
        "#6E8C9C",
    )
    assert PSEUDO_CATEGORIES == ("All", "Unassigned")
    assert isinstance(DEFAULT_CATEGORIES, tuple)


# ----------------------------------------------------------------- normalize_hex_color


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("#abcdef", "#ABCDEF"),
        ("abcdef", "#ABCDEF"),
        (" #ABCDEF ", "#ABCDEF"),
        ("#5F8B7E", "#5F8B7E"),
        ("123456", "#123456"),
    ],
)
def test_normalize_hex_color_accepts(raw: str, expected: str) -> None:
    assert normalize_hex_color(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "   ", "#abc", "#GGGGGG", "#abcdef0", "abcde", "##abcdef", "#abc def"]
)
def test_normalize_hex_color_rejects(raw: str) -> None:
    assert not normalize_hex_color(raw)


# ----------------------------------------------------------------- categories / priority / colors


def test_get_categories_contract() -> None:
    result = get_categories(
        ["UI", "All", "Unassigned", "", "Custom A", "ui"],
        ["Overhaul", "custom a", "UI"],
        ["Skins", "Overhaul", "", "Unassigned", "Districts"],
    )
    assert result == ("UI", "Custom A", "Overhaul", "Skins", "Districts")
    assert isinstance(result, tuple)
    assert get_categories([], [], []) == ()
    assert get_categories(DEFAULT_CATEGORIES, (), {}.values()) == DEFAULT_CATEGORIES


def test_get_category_priority_contract() -> None:
    priority = get_category_priority(("Class", "UI", "Overhaul"), BASE_PRIORITY)
    assert priority["Class"] == 0 and priority["UI"] == 100 and priority["Overhaul"] == 200
    assert priority["Skins"] == 600  # base fills the rest
    assert priority["Unassigned"] == 700
    assert get_category_priority((), {}, fallback=42) == {"Unassigned": 42}
    assert get_category_priority(("Unassigned",), {}, fallback=42)["Unassigned"] == 0


def test_category_color_contract() -> None:
    colors = {"Overhaul": "5f8b7e", "UI": "bad", "Class": " #A66A4A "}
    assert category_color("Overhaul", colors, FALLBACK) == "#5F8B7E"
    assert category_color("UI", colors, FALLBACK) == "#8FA6B8"  # invalid user color -> builtin
    assert category_color("Class", colors, FALLBACK) == "#A66A4A"
    assert category_color("Skins", colors, FALLBACK) == "#9D7A9A"
    assert category_color("Unknown", colors, FALLBACK) == FALLBACK
    assert category_color("Unassigned", {}, FALLBACK) == "#82786B"


def test_default_color_for_new_category_contract() -> None:
    assert default_color_for_new_category({}, FALLBACK) == "#5F8B7E"
    assert default_color_for_new_category({"X": "5f8b7e"}, FALLBACK) == "#A66A4A"
    everything = {f"c{i}": color for i, color in enumerate(CATEGORY_COLOR_CYCLE)}
    assert (
        default_color_for_new_category(everything, FALLBACK) == "#5F8B7E"
    )  # cycle exhausted -> first
    assert default_color_for_new_category({"X": "bad"}, FALLBACK) == "#5F8B7E"


# ----------------------------------------------------------------- move operations


def test_move_category_contract() -> None:
    assert move_category(("a", "b", "c"), 0, 1) == ("b", "a", "c")
    assert move_category(("a", "b", "c"), 2, -1) == ("a", "c", "b")
    assert move_category(("a", "b", "c"), 0, -1) == ("a", "b", "c")
    assert move_category(("a", "b", "c"), 2, 1) == ("a", "b", "c")
    assert move_category(("a", "b", "c"), 5, 1) == ("a", "b", "c")
    assert move_category(("a", "b", "c"), -1, 1) == ("a", "b", "c")
    assert move_category((), 0, 1) == ()
    assert move_category(["a", "b"], 0, 1) == ("b", "a")
    assert isinstance(move_category(("a", "b"), 0, 1), tuple)


def test_move_category_to_index_contract() -> None:
    assert move_category_to_index(("a", "b", "c", "d"), 0, 2) == ("b", "c", "a", "d")
    assert move_category_to_index(("a", "b", "c", "d"), 3, 0) == ("d", "a", "b", "c")
    assert move_category_to_index(("a", "b", "c"), 1, 1) == ("a", "b", "c")
    assert move_category_to_index(("a", "b", "c"), 1, 3) == ("a", "b", "c")
    assert move_category_to_index(("a", "b", "c"), 3, 1) == ("a", "b", "c")
    assert move_category_to_index(("a", "b", "c"), -1, 1) == ("a", "b", "c")


def test_move_operations_do_not_mutate_the_input() -> None:
    items = ["a", "b", "c"]
    move_category(items, 0, 1)
    move_category_to_index(items, 0, 2)
    assert items == ["a", "b", "c"]


# ----------------------------------------------------------------- editor state and operations


def _editor(
    categories: Sequence[str] = DEFAULT_CATEGORIES,
    custom: Sequence[str] = (),
    colors: Mapping[str, str] | None = None,
) -> CategoryEditorState:
    return CategoryEditorState(
        categories=tuple(categories),
        custom_categories=tuple(custom),
        category_colors=dict(colors or {}),
        renamed={},
        removed=(),
    )


def test_editor_state_is_a_frozen_value() -> None:
    state = _editor()
    assert dataclasses.is_dataclass(state) and hasattr(state, "__slots__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.categories = ()  # ty: ignore[invalid-assignment]
    assert [f.name for f in dataclasses.fields(CategoryEditorState)] == [
        "categories",
        "custom_categories",
        "category_colors",
        "renamed",
        "removed",
    ]
    assert [f.name for f in dataclasses.fields(CategoryChanges)] == [
        "category_order",
        "custom_categories",
        "category_colors",
        "assignments",
        "category_memory",
    ]


def test_add_rename_remove_are_functional() -> None:
    start = _editor()
    added = add_custom_category(start, "Overhaul", "#5F8B7E")
    assert start.categories == DEFAULT_CATEGORIES  # untouched
    assert added.categories == (*DEFAULT_CATEGORIES, "Overhaul")
    assert added.custom_categories == ("Overhaul",)
    assert added.category_colors == {"Overhaul": "#5F8B7E"}
    index = added.categories.index("Overhaul")
    renamed = rename_custom_category(added, index, "Overhaul", "Total Overhaul")
    assert renamed.categories[index] == "Total Overhaul"
    assert set(renamed.custom_categories) == {"Total Overhaul"}
    assert renamed.category_colors == {"Total Overhaul": "#5F8B7E"}
    assert dict(renamed.renamed) == {"Total Overhaul": "Overhaul"}
    again = rename_custom_category(renamed, index, "Total Overhaul", "Final")
    assert dict(again.renamed) == {"Final": "Overhaul"}  # chained renames keep the original
    removed = remove_custom_category(again, index, "Final")
    assert removed.categories == DEFAULT_CATEGORIES
    assert removed.custom_categories == ()
    assert removed.category_colors == {}
    assert "Final" in removed.removed


def test_apply_changes_contract() -> None:
    state = CategoryEditorState(
        categories=("Class", "UI", "Big Mod", "Skins"),
        custom_categories=("Big Mod",),
        category_colors={"Big Mod": "5f8b7e", "UI": "bad", "Skins": "#A66A4A", "Gone": "#7D8FB3"},
        renamed={"Big Mod": "Overhaul"},
        removed=("Temp",),
    )
    assignments = {
        ModId("a"): "Overhaul",
        ModId("b"): "Temp",
        ModId("c"): "Class",
        ModId("d"): "UI",
    }
    memory = {"k1": "Overhaul", "norm:k1": "Overhaul", "k2": "Temp", "k3": "Class"}
    changes = apply_category_editor_changes(state, assignments=assignments, category_memory=memory)
    assert isinstance(changes, CategoryChanges)
    assert changes.category_order == ("Class", "UI", "Big Mod", "Skins")
    assert changes.custom_categories == ("Big Mod",)
    assert changes.category_colors == {"Big Mod": "#5F8B7E", "Skins": "#A66A4A"}
    effective = {m: v for m, v in {**assignments, **changes.assignments}.items() if v is not None}
    assert effective == {ModId("a"): "Big Mod", ModId("c"): "Class", ModId("d"): "UI"}
    assert changes.assignments.get(ModId("b"), None) is None  # removed custom -> unassigned
    assert changes.category_memory == {"k1": "Big Mod", "norm:k1": "Big Mod", "k3": "Class"}
    assert assignments[ModId("a")] == "Overhaul" and memory["k2"] == "Temp"  # inputs untouched


def test_dedupe_category_names_is_the_one_shared_pass() -> None:
    """Blanks and pseudo categories are dropped, repeats folded
    case-insensitively with ``str.lower`` (``tiers`` and ``state_file`` reuse this)."""
    names = dedupe_category_names(("Class", "", "All", "class", "Unassigned"), ("Lore", "CLASS"))
    assert names == ("Class", "Lore")
    assert dedupe_category_names() == ()
    assert dedupe_category_names(("ß", "SS")) == ("ß", "SS")  # lower(), not casefold()
    assert get_categories(("UI",), ("ui", "Lore"), ("lore", "Class")) == ("UI", "Lore", "Class")


def test_apply_changes_rename_then_remove_unassigns_and_purges_memory() -> None:
    """``A`` renamed to ``B`` and ``B`` removed in one session: nothing may stay on ``A`` or ``B``
    (a stale rename pair must not leave mods or memory on the vanished ``B``)."""
    state = _editor([*DEFAULT_CATEGORIES, "A"], ("A",))
    index = state.categories.index("A")
    state = rename_custom_category(state, index, "A", "B")
    state = remove_custom_category(state, index, "B")
    assert state.renamed == {"B": "A"}
    assert state.removed == ("B",)
    changes = apply_category_editor_changes(
        state,
        assignments={ModId("m"): "A", ModId("n"): "Class"},
        category_memory={"k": "A", "k2": "Class"},
    )
    assert changes.assignments == {ModId("m"): None}
    assert changes.category_memory == {"k2": "Class"}
    assert "A" not in changes.category_order and "B" not in changes.category_order
    assert changes.custom_categories == ()


def test_apply_changes_rename_then_remove_from_literal_state() -> None:
    state = CategoryEditorState(
        categories=DEFAULT_CATEGORIES,
        custom_categories=(),
        category_colors={},
        renamed={"B": "A"},
        removed=("B",),
    )
    changes = apply_category_editor_changes(
        state, assignments={ModId("m"): "A"}, category_memory={"k": "A"}
    )
    assert changes.assignments == {ModId("m"): None}
    assert changes.category_memory == {}


def test_apply_changes_with_nothing_edited_is_identity() -> None:
    state = _editor((*DEFAULT_CATEGORIES, "Patch"), ("Patch",), {"Patch": "#5F8B7E"})
    assignments = {ModId("a"): "Patch", ModId("b"): "Class"}
    memory = {"x": "Patch"}
    changes = apply_category_editor_changes(state, assignments=assignments, category_memory=memory)
    assert changes.category_order == (*DEFAULT_CATEGORIES, "Patch")
    assert changes.custom_categories == ("Patch",)
    assert changes.category_colors == {"Patch": "#5F8B7E"}
    effective = {m: v for m, v in {**assignments, **changes.assignments}.items() if v is not None}
    assert effective == assignments
    assert changes.category_memory == memory
