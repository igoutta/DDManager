"""Tiers (src/core/tiers.py): precedence classes derived from the categories.

Weights live in precedence space (higher wins): overhaul 0 < category_order positions
(i+1)*100 < unassigned < patch."""

import random

import pytest

from src.core.tiers import (
    BUILTIN_TIER_IDS,
    CATEGORY_TO_TIER,
    Tier,
    TierResolution,
    TierTable,
    resolve_tier,
)

# The built-in categories (inlined so this file does not depend on src/core/categories.py)
DEFAULT_CATEGORIES = (
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
CUSTOM_POOL = ("Lore", "Music", "Fonts", "Camping")


def _default_table() -> TierTable:
    return TierTable.from_categories(DEFAULT_CATEGORIES, ())


# ----------------------------------------------------------------- constants


def test_builtin_ids_and_category_mapping_are_exact() -> None:
    assert BUILTIN_TIER_IDS == (
        "overhaul",
        "ui",
        "district",
        "dungeon",
        "quirk",
        "item",
        "enemy",
        "class_patch",
        "class",
        "skin",
        "patch",
        "unassigned",
    )
    assert dict(CATEGORY_TO_TIER) == {
        "UI": "ui",
        "Districts": "district",
        "Dungeons": "dungeon",
        "Quirks": "quirk",
        "Trinkets": "item",
        "Enemies": "enemy",
        "Class Patch": "class_patch",
        "Class": "class",
        "Skins": "skin",
        "Overhaul": "overhaul",
        "Patch": "patch",
    }
    assert set(CATEGORY_TO_TIER.values()) <= set(BUILTIN_TIER_IDS)


def test_tier_is_a_frozen_value() -> None:
    tier = Tier("ui", 100, "UI", True)
    assert tier == Tier(id="ui", weight=100, category="UI", builtin=True)
    with pytest.raises((AttributeError, TypeError)):
        tier.weight = 5  # ty: ignore[invalid-assignment]


# ----------------------------------------------------------------- from_categories


def test_from_categories_default_weights_are_exact() -> None:
    table = _default_table()
    assert {t.id: t.weight for t in table.tiers} == {
        "overhaul": 0,
        "ui": 100,
        "district": 200,
        "dungeon": 300,
        "quirk": 400,
        "item": 500,
        "enemy": 600,
        "class_patch": 700,
        "class": 800,
        "skin": 900,
        "unassigned": 1000,
        "patch": 1100,
    }
    assert all(t.builtin for t in table.tiers)
    assert len(table.tiers) == len(BUILTIN_TIER_IDS)


def test_builtin_tiers_carry_their_category() -> None:
    table = _default_table()
    assert table.get("ui").category == "UI"
    assert table.get("class_patch").category == "Class Patch"
    assert table.get("item").category == "Trinkets"
    assert table.get("skin").category == "Skins"


def test_get_unknown_id_returns_the_unassigned_tier() -> None:
    table = _default_table()
    unassigned = table.get("unassigned")
    assert unassigned.id == "unassigned"
    assert table.get("nope") == unassigned
    assert table.get("") == unassigned
    assert table.get("custom:Nope") == unassigned


def test_for_category_maps_builtin_names_and_pseudo_categories() -> None:
    table = _default_table()
    assert table.for_category(None) == table.get("unassigned")
    assert table.for_category("Unassigned") == table.get("unassigned")
    assert table.for_category("UI").id == "ui"
    assert table.for_category("Class Patch").id == "class_patch"
    assert table.for_category("Class").id == "class"
    assert table.for_category("Skins").id == "skin"
    assert table.for_category("Trinkets").id == "item"


def test_overhaul_and_patch_customs_map_to_builtins_case_insensitively() -> None:
    table = TierTable.from_categories(DEFAULT_CATEGORIES, ("overhaul", "PATCH"))
    assert table.for_category("overhaul").id == "overhaul"
    assert table.for_category("Overhaul").id == "overhaul"
    assert table.for_category("PATCH").id == "patch"
    assert table.for_category("Patch").id == "patch"
    assert not any(t.id.startswith("custom:") for t in table.tiers)
    assert table.get("overhaul").weight == 0
    assert table.get("patch").weight > table.get("unassigned").weight
    assert table.get("unassigned").weight > table.get("skin").weight


def test_custom_category_gets_a_position_weight_after_the_default_order() -> None:
    table = TierTable.from_categories(DEFAULT_CATEGORIES, ("Lore", "Overhaul"))
    lore = table.for_category("Lore")
    assert lore == Tier("custom:Lore", 1000, "Lore", False)
    assert table.get("custom:Lore") == lore
    assert lore in table.tiers
    assert table.get("skin").weight < lore.weight < table.get("unassigned").weight
    assert table.get("unassigned").weight < table.get("patch").weight
    assert table.get("overhaul").weight == 0


def test_custom_category_inside_category_order_takes_that_position() -> None:
    order = ("UI", "Lore", *DEFAULT_CATEGORIES[1:])
    table = TierTable.from_categories(order, ("Lore",))
    assert table.for_category("UI").weight == 100
    assert table.for_category("Lore").weight == 200
    assert table.for_category("Districts").weight == 300
    assert table.for_category("Skins").weight == 1000
    assert table.get("unassigned").weight == 1100
    assert table.get("patch").weight == 1200


def test_from_categories_with_a_shuffled_category_order_follows_that_order() -> None:
    rng = random.Random(7)
    for _ in range(50):
        order = list(DEFAULT_CATEGORIES)
        rng.shuffle(order)
        table = TierTable.from_categories(order, ())
        assert [table.for_category(c).weight for c in order] == [
            (i + 1) * 100 for i in range(len(order))
        ]
        assert {t.id for t in table.tiers} == set(BUILTIN_TIER_IDS)


def test_every_tier_id_is_unique_and_weights_are_strictly_ordered_by_position() -> None:
    table = TierTable.from_categories(DEFAULT_CATEGORIES, CUSTOM_POOL)
    ids = [t.id for t in table.tiers]
    assert len(ids) == len(set(ids))
    positions = [*DEFAULT_CATEGORIES, *CUSTOM_POOL]
    weights = [table.for_category(c).weight for c in positions]
    assert weights == sorted(weights)
    assert len(set(weights)) == len(weights)
    assert table.get("overhaul").weight < weights[0]
    assert weights[-1] < table.get("unassigned").weight < table.get("patch").weight


# ----------------------------------------------------------------- resolve_tier


def test_resolve_tier_precedence_rules_then_category_then_classifier_then_default() -> None:
    table = TierTable.from_categories(DEFAULT_CATEGORIES, ("Lore",))
    assert resolve_tier(
        rules_tier="patch", category="Class", suggestion="Dungeons", table=table
    ) == TierResolution(table.get("patch"), "rules")
    assert resolve_tier(
        rules_tier=None, category="Class", suggestion="Dungeons", table=table
    ) == TierResolution(table.get("class"), "category")
    assert resolve_tier(
        rules_tier=None, category=None, suggestion="Dungeons", table=table
    ) == TierResolution(table.get("dungeon"), "classifier")
    assert resolve_tier(
        rules_tier=None, category=None, suggestion=None, table=table
    ) == TierResolution(table.get("unassigned"), "default")
    assert resolve_tier(
        rules_tier=None, category="Lore", suggestion="UI", table=table
    ) == TierResolution(table.get("custom:Lore"), "category")
    assert resolve_tier(
        rules_tier="overhaul", category=None, suggestion=None, table=table
    ) == TierResolution(table.get("overhaul"), "rules")


def test_tier_resolution_is_a_frozen_value() -> None:
    table = _default_table()
    resolution = resolve_tier(rules_tier=None, category=None, suggestion=None, table=table)
    assert resolution.reason == "default"
    with pytest.raises((AttributeError, TypeError)):
        resolution.reason = "rules"  # ty: ignore[invalid-assignment]
