"""Tiers: the precedence classes that replace the legacy category sort buckets.

The legacy Auto-Sort (``dd2.py:4327-4353`` ``sorted_order_by_category``) bucketed mods by
category through ``categories.get_category_priority`` (``categories.py:67-79``): every category
in ``category_order`` got ``index * 100``, missing ones their base value, and ``Unassigned``
was forced last. :meth:`TierTable.from_legacy` keeps that bucket order but expresses it in
PRECEDENCE space (higher weight wins conflicts): ``overhaul`` is the base at ``0``, the ordered
categories follow at ``(i + 1) * 100``, then ``unassigned`` and finally ``patch`` (patches
always win). ``Overhaul`` and ``Patch`` are recognised as custom categories by case-insensitive
name and never take a position of their own.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

from src.core.categories import PSEUDO_CATEGORIES, dedupe_category_names

BUILTIN_TIER_IDS: Final = (
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
OVERHAUL_TIER_ID: Final = "overhaul"
PATCH_TIER_ID: Final = "patch"
CLASS_PATCH_TIER_ID: Final = "class_patch"
UNASSIGNED_TIER_ID: Final = "unassigned"
CUSTOM_PREFIX: Final = "custom:"

LEGACY_CATEGORY_TO_TIER: Final[Mapping[str, str]] = MappingProxyType(
    {
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
)
_ANCHORS: Final[Mapping[str, str]] = MappingProxyType(
    {"overhaul": OVERHAUL_TIER_ID, "patch": PATCH_TIER_ID}
)
"""Casefolded custom-category names that map to the fixed bottom/top tiers."""
_POSITIONED_LEGACY: Final = tuple(
    (name, tier_id)
    for name, tier_id in LEGACY_CATEGORY_TO_TIER.items()
    if tier_id not in _ANCHORS.values()
)
_TIER_SPAN: Final = 100

type TierReason = Literal["rules", "legacy", "classifier", "default"]


@dataclass(frozen=True, slots=True)
class Tier:
    """A precedence class: higher ``weight`` wins conflicts against lower ones."""

    id: str
    weight: int
    legacy_category: str | None
    builtin: bool


@dataclass(frozen=True, slots=True)
class TierResolution:
    tier: Tier
    reason: TierReason


def _builtin_tier_id_for_category(category: str) -> str | None:
    """The builtin tier id a legacy category name denotes (``Overhaul``/``Patch`` by casefold)."""
    return LEGACY_CATEGORY_TO_TIER.get(category) or _ANCHORS.get(category.casefold())


def _tier_for_category(name: str, weight: int) -> Tier:
    tier_id = LEGACY_CATEGORY_TO_TIER.get(name)
    if tier_id is None:
        return Tier(f"{CUSTOM_PREFIX}{name}", weight, name, builtin=False)
    return Tier(tier_id, weight, name, builtin=True)


def _positioned_names(category_order: Sequence[str], custom_categories: Sequence[str]) -> list[str]:
    """Category names that take a position, in ``categories.py:44-65`` order, anchors left out."""
    return [
        name
        for name in dedupe_category_names(category_order, custom_categories)
        if name.casefold() not in _ANCHORS
    ]


def _positioned_tiers(names: Sequence[str]) -> list[Tier]:
    """Tiers for ``names`` at ``(i + 1) * 100``, then any legacy category the order left out."""
    tiers = [_tier_for_category(name, (index + 1) * _TIER_SPAN) for index, name in enumerate(names)]
    present = {tier.id for tier in tiers}
    for name, tier_id in _POSITIONED_LEGACY:
        if tier_id not in present:
            tiers.append(Tier(tier_id, (len(tiers) + 1) * _TIER_SPAN, name, builtin=True))
            present.add(tier_id)
    return tiers


@dataclass(frozen=True, slots=True)
class TierTable:
    """Every tier of a configuration; lookups fall back to the ``unassigned`` tier."""

    tiers: tuple[Tier, ...]

    def _by_id(self) -> dict[str, Tier]:
        return {tier.id: tier for tier in self.tiers}

    def unassigned(self) -> Tier:
        return self._by_id()[UNASSIGNED_TIER_ID]

    def get(self, tier_id: str) -> Tier:
        """The tier with ``tier_id``; unknown ids resolve to the unassigned tier."""
        return self._by_id().get(tier_id, self.unassigned())

    def for_category(self, category: str | None) -> Tier:
        """The tier of a legacy category: ``None``/``"Unassigned"`` -> unassigned; builtin names
        map through :data:`LEGACY_CATEGORY_TO_TIER`; any other name is ``custom:<name>``. A custom
        category the table does not know resolves to unassigned (``categories.py:79`` fallback).
        """
        if category is None or category in PSEUDO_CATEGORIES:
            return self.unassigned()
        builtin = _builtin_tier_id_for_category(category)
        return self.get(builtin if builtin is not None else f"{CUSTOM_PREFIX}{category}")

    @classmethod
    def from_legacy(
        cls, category_order: Sequence[str], custom_categories: Sequence[str]
    ) -> TierTable:
        """Build the table from the legacy ``category_order`` / ``custom_categories`` lists.

        ``overhaul`` = 0; each positioned category (``category_order`` first, then customs not in
        it, like ``categories.py:44-65``) gets ``(i + 1) * 100``; legacy categories the order
        left out are appended after them; ``unassigned`` = ``(n + 1) * 100``; ``patch`` =
        ``(n + 2) * 100``.
        """
        positioned = _positioned_tiers(_positioned_names(category_order, custom_categories))
        count = len(positioned)
        tiers = (
            Tier(OVERHAUL_TIER_ID, 0, "Overhaul", builtin=True),
            *positioned,
            Tier(UNASSIGNED_TIER_ID, (count + 1) * _TIER_SPAN, None, builtin=True),
            Tier(PATCH_TIER_ID, (count + 2) * _TIER_SPAN, "Patch", builtin=True),
        )
        return cls(tiers)


def resolve_tier(
    *,
    rules_tier: str | None,
    legacy_category: str | None,
    suggestion: str | None,
    table: TierTable,
) -> TierResolution:
    """Pick a mod's tier: rules file, then legacy category, then classifier, then default."""
    if rules_tier is not None:
        return TierResolution(table.get(rules_tier), "rules")
    if legacy_category is not None:
        return TierResolution(table.for_category(legacy_category), "legacy")
    if suggestion is not None:
        return TierResolution(table.for_category(suggestion), "classifier")
    return TierResolution(table.unassigned(), "default")
