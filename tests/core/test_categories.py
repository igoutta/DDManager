"""The legacy category system with explicit arguments (src/core/categories.py).

Contract: the constants are verbatim categories.py:7-42; ``get_categories`` (44-65),
``get_category_priority`` (67-79), ``category_color`` (82-87), ``default_color_for_new_category``
(91-100) and ``normalize_hex_color`` (dd2.py:623-631) take their inputs explicitly instead of the
state dict; the editor operations (292-342) are functional over ``CategoryEditorState`` and
``apply_category_editor_changes`` (344-384) returns a ``CategoryChanges`` instead of mutating.

Unspecified call shapes resolved here (mirroring the legacy positional tails after the state):
``add_custom_category(state, name, color)``, ``rename_custom_category(state, index, old, new)``,
``remove_custom_category(state, index, name)``; ``CategoryEditorState.renamed`` maps new name ->
original name like the legacy ``renamed_categories`` dict; ``removed`` lists the customs removed
through ``remove_custom_category`` so ``apply_category_editor_changes`` can unassign them. The
random sessions never remove a category that was renamed in the same session: the legacy keeps
the stale rename pair and leaves mods on the vanished name (categories.py:366-368), a bug not
worth porting.
"""

import dataclasses
import random
from collections.abc import Mapping, Sequence
from types import ModuleType
from typing import Any

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
from tools.legacy_oracle import LegacyOracle

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
NAME_POOL = (
    "UI",
    "ui",
    "Districts",
    "Dungeons",
    "Class",
    "Skins",
    "Overhaul",
    "overhaul",
    "Patch",
    "All",
    "Unassigned",
    "all",
    "unassigned",
    "",
    "Custom A",
    "custom a",
    "Custom B",
)
COLOR_POOL = ("#5F8B7E", "5f8b7e", "#A66A4A", "", "bad", "#abc", " #7D8FB3 ", "#A46D8A", "#9F9153")


# ----------------------------------------------------------------- constants


def test_constants_are_the_legacy_values() -> None:
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


@pytest.mark.legacy
def test_constants_match_legacy(legacy: LegacyOracle) -> None:
    cat = legacy.module("categories")
    assert list(DEFAULT_CATEGORIES) == cat.DEFAULT_CATEGORIES
    assert dict(CATEGORY_COLORS) == cat.CATEGORY_COLORS
    assert list(CATEGORY_COLOR_CYCLE) == cat.CATEGORY_COLOR_CYCLE


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


@pytest.mark.legacy
def test_normalize_hex_color_matches_legacy(legacy: LegacyOracle) -> None:
    dd2 = legacy.module("dd2")
    rng = random.Random(4)
    alphabet = "0123456789abcdefABCDEFg# "
    samples = ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 9))) for _ in range(1000)]
    for raw in (*samples, *COLOR_POOL):
        assert (normalize_hex_color(raw) or "") == dd2.normalize_hex_color(raw), repr(raw)


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


def _random_state(rng: random.Random) -> dict[str, Any]:
    return {
        "category_order": [rng.choice(NAME_POOL) for _ in range(rng.randint(0, 8))],
        "custom_categories": [rng.choice(NAME_POOL) for _ in range(rng.randint(0, 4))],
        "categories": {f"m{i}": rng.choice(NAME_POOL) for i in range(rng.randint(0, 6))},
        "category_colors": {
            rng.choice(NAME_POOL): rng.choice(COLOR_POOL) for _ in range(rng.randint(0, 5))
        },
    }


@pytest.mark.legacy
def test_get_categories_and_priority_match_legacy(legacy: LegacyOracle) -> None:
    cat = legacy.module("categories")
    rng = random.Random(8)
    for _ in range(300):
        state = _random_state(rng)
        got = get_categories(
            state["category_order"], state["custom_categories"], state["categories"].values()
        )
        assert list(got) == cat.get_categories(state)
        fallback = rng.choice((700, 42))
        assert get_category_priority(got, BASE_PRIORITY, fallback) == cat.get_category_priority(
            state, BASE_PRIORITY, fallback
        )


@pytest.mark.legacy
def test_colors_match_legacy(legacy: LegacyOracle) -> None:
    cat = legacy.module("categories")
    dd2 = legacy.module("dd2")
    rng = random.Random(9)
    for _ in range(300):
        state = _random_state(rng)
        colors = state["category_colors"]
        for name in (*NAME_POOL, "Quirks"):
            assert category_color(name, colors, FALLBACK) == cat.category_color(
                state, name, dd2.normalize_hex_color, FALLBACK
            )
        assert default_color_for_new_category(
            colors, FALLBACK
        ) == cat.default_color_for_new_category(state, dd2.normalize_hex_color, FALLBACK)


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


@pytest.mark.legacy
def test_move_operations_match_legacy(legacy: LegacyOracle) -> None:
    cat = legacy.module("categories")
    rng = random.Random(10)
    for _ in range(500):
        items = [f"c{i}" for i in range(rng.randint(0, 6))]
        index = rng.randint(-2, 7)
        if rng.random() < 0.5:
            delta = rng.choice((-1, 1, 2, -3))
            mirror = list(items)
            cat.move_category(mirror, index, delta)
            assert list(move_category(items, index, delta)) == mirror, (items, index, delta)
        else:
            target = rng.randint(-2, 7)
            mirror = list(items)
            cat.move_category_to_index(mirror, index, target)
            assert list(move_category_to_index(items, index, target)) == mirror, (
                items,
                index,
                target,
            )


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
    """categories.py:49-63 / state.py:47-53: blanks and pseudo categories dropped, repeats folded
    case-insensitively with ``str.lower`` (``tiers`` and ``legacy_state`` reuse this)."""
    names = dedupe_category_names(("Class", "", "All", "class", "Unassigned"), ("Lore", "CLASS"))
    assert names == ("Class", "Lore")
    assert dedupe_category_names() == ()
    assert dedupe_category_names(("ß", "SS")) == ("ß", "SS")  # lower(), not casefold()
    assert get_categories(("UI",), ("ui", "Lore"), ("lore", "Class")) == ("UI", "Lore", "Class")


def test_apply_changes_rename_then_remove_unassigns_and_purges_memory() -> None:
    """``A`` renamed to ``B`` and ``B`` removed in one session: nothing may stay on ``A`` or ``B``
    (the legacy left mods and memory on the vanished ``B``, see the regression lock below)."""
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


@pytest.mark.legacy
def test_regression_lock_legacy_leaves_mods_on_a_renamed_then_removed_category(
    legacy: LegacyOracle,
) -> None:
    """categories.py:366-368 keeps the stale rename pair, so the legacy moves ``m`` to the
    removed ``B``; the port unassigns it (``test_apply_changes_rename_then_remove_...``)."""
    cat = legacy.module("categories")
    dd2 = legacy.module("dd2")
    categories = [*DEFAULT_CATEGORIES, "A"]
    custom, colors, renamed = {"A"}, {}, {}
    index = categories.index("A")
    cat.rename_custom_category(categories, custom, colors, renamed, index, "A", "B")
    cat.remove_custom_category(categories, custom, colors, index, "B")
    legacy_state = {
        "custom_categories": ["A"],
        "categories": {"m": "A"},
        "category_memory": {"k": "A"},
    }
    cat.apply_category_editor_changes(
        legacy_state, categories, colors, renamed, dd2.normalize_hex_color
    )
    assert legacy_state["categories"] == {"m": "B"}  # dangling: B no longer exists
    assert legacy_state["category_memory"] == {"k": "B"}
    assert "B" not in legacy_state["category_order"]
    state = _editor([*DEFAULT_CATEGORIES, "A"], ("A",))
    state = remove_custom_category(rename_custom_category(state, index, "A", "B"), index, "B")
    changes = apply_category_editor_changes(
        state, assignments={ModId("m"): "A"}, category_memory={"k": "A"}
    )
    assert changes.assignments == {ModId("m"): None}
    assert changes.category_memory == {}
    assert list(changes.category_order) == legacy_state["category_order"]


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


# ----------------------------------------------------------------- editor parity (random sessions)


class _LegacyEditor:
    """The four working objects of the legacy "Edit Categories" dialog (dd2.py:5308-5314)."""

    def __init__(
        self,
        cat: ModuleType,
        categories: Sequence[str],
        custom: Sequence[str],
        colors: Mapping[str, str],
    ) -> None:
        self.cat = cat
        self.categories = list(categories)
        self.custom = set(custom)
        self.colors = dict(colors)
        self.renamed: dict[str, str] = {}

    def snapshot(self) -> tuple[list[str], set[str], dict[str, str], dict[str, str]]:
        return (list(self.categories), set(self.custom), dict(self.colors), dict(self.renamed))


def _state_snapshot(
    state: CategoryEditorState,
) -> tuple[list[str], set[str], dict[str, str], dict[str, str]]:
    return (
        list(state.categories),
        set(state.custom_categories),
        dict(state.category_colors),
        dict(state.renamed),
    )


def _apply_random_op(
    rng: random.Random, legacy: _LegacyEditor, state: CategoryEditorState, counter: int
) -> CategoryEditorState:
    customs = [c for c in legacy.categories if c in legacy.custom]
    choice = rng.random()
    if choice < 0.3 or not customs:
        name = f"Custom {counter}"
        color = rng.choice(COLOR_POOL)
        legacy.cat.add_custom_category(legacy.categories, legacy.custom, legacy.colors, name, color)
        return add_custom_category(state, name, color)
    if choice < 0.5:
        old = rng.choice(customs)
        index = legacy.categories.index(old)
        new = f"Renamed {counter}"
        legacy.cat.rename_custom_category(
            legacy.categories, legacy.custom, legacy.colors, legacy.renamed, index, old, new
        )
        return rename_custom_category(state, index, old, new)
    removable = [c for c in customs if c not in legacy.renamed]  # see module docstring
    if choice < 0.65 and removable:
        name = rng.choice(removable)
        index = legacy.categories.index(name)
        legacy.cat.remove_custom_category(
            legacy.categories, legacy.custom, legacy.colors, index, name
        )
        return remove_custom_category(state, index, name)
    index = rng.randrange(len(legacy.categories))
    if choice < 0.85:
        delta = rng.choice((-1, 1))
        legacy.cat.move_category(legacy.categories, index, delta)
        return dataclasses.replace(state, categories=move_category(state.categories, index, delta))
    target = rng.randrange(len(legacy.categories))
    legacy.cat.move_category_to_index(legacy.categories, index, target)
    return dataclasses.replace(
        state, categories=move_category_to_index(state.categories, index, target)
    )


def _random_session(
    rng: random.Random, cat: ModuleType, steps: int
) -> tuple[_LegacyEditor, CategoryEditorState, dict[str, Any]]:
    customs = ["Overhaul", "Patch"][: rng.randint(0, 2)]
    categories = [*DEFAULT_CATEGORIES, *customs]
    raw_colors = {c: rng.choice(COLOR_POOL) for c in rng.sample(categories, rng.randint(0, 4))}
    colors = {c: normalize_hex_color(v) or "" for c, v in raw_colors.items()}
    colors = {c: v for c, v in colors.items() if v}
    legacy_state = {
        "custom_categories": list(customs),
        "categories": {
            f"m{i}": rng.choice([*categories, "Unassigned"]) for i in range(rng.randint(0, 8))
        },
        "category_memory": {f"k{i}": rng.choice(categories) for i in range(rng.randint(0, 8))},
    }
    legacy = _LegacyEditor(cat, categories, customs, colors)
    state = _editor(categories, customs, colors)
    for step in range(steps):
        state = _apply_random_op(rng, legacy, state, step)
        assert _state_snapshot(state) == legacy.snapshot(), step
    return legacy, state, legacy_state


@pytest.mark.legacy
def test_editor_sessions_match_legacy(legacy: LegacyOracle) -> None:
    cat = legacy.module("categories")
    dd2 = legacy.module("dd2")
    rng = random.Random(12)
    for _ in range(150):
        editor, state, legacy_state = _random_session(rng, cat, rng.randint(0, 10))
        assignments = {ModId(m): c for m, c in legacy_state["categories"].items()}
        memory = dict(legacy_state["category_memory"])
        changes = apply_category_editor_changes(
            state, assignments=assignments, category_memory=memory
        )
        final = cat.apply_category_editor_changes(
            legacy_state, editor.categories, editor.colors, editor.renamed, dd2.normalize_hex_color
        )
        assert list(changes.category_order) == final == legacy_state["category_order"]
        assert list(changes.custom_categories) == legacy_state["custom_categories"]
        assert dict(changes.category_colors) == legacy_state["category_colors"]
        effective = {
            m: v for m, v in {**assignments, **changes.assignments}.items() if v is not None
        }
        assert {str(m): v for m, v in effective.items()} == legacy_state["categories"]
        assert dict(changes.category_memory) == legacy_state["category_memory"]
