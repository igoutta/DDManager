"""Resolving a rules document against the installed mods: refs become ``ModId`` relations.

The on-disk format lives in :mod:`src.core.rules_format`; this module turns its refs into
precedence edges, requirement lists, incompatible pairs, compatible sets and tier overrides, and
answers the overlap policy of a path.
"""

import re
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import translate
from functools import cache
from typing import Final

from src.core.identity_text import normalize_mod_identity
from src.core.ids import ModId
from src.core.model import ModInfo
from src.core.rules_format import ModRule, RulesData
from src.core.sorting import PrecedenceEdge

EDGE_REQUIRES: Final = "requires"
EDGE_LOAD_AFTER: Final = "load_after"
EDGE_PATCH_FOR: Final = "patch_for"


class OverlapPolicy(StrEnum):
    """What a shared relative path means for two mods that both ship it."""

    OVERRIDE = "override"
    MERGE = "merge"
    IGNORE = "ignore"


def match_ref(ref: str, info: ModInfo) -> bool:
    """Whether an installed mod is the one a ModRef points at."""
    kind, _, value = ref.partition(":")
    if kind == "steam":
        return (info.save_identity.is_workshop and info.save_identity.name == value) or (
            bool(value) and info.workshop_id == value
        )
    if kind == "local":
        return not info.save_identity.is_workshop and (
            normalize_mod_identity(info.save_identity.name) == normalize_mod_identity(value)
        )
    if kind == "title":
        return normalize_mod_identity(info.title) == normalize_mod_identity(value)
    return kind == "key" and info.id == value


@cache
def _pattern_matcher(patterns: tuple[str, ...]) -> Callable[[str], bool]:
    """One compiled matcher for a whole pattern list (``fnmatchcase`` semantics, casefolded)."""
    if not patterns:
        return lambda _path: False
    regex = re.compile("|".join(f"(?:{translate(pattern.casefold())})" for pattern in patterns))
    return lambda path: regex.match(path) is not None


@dataclass(frozen=True, slots=True)
class ResolvedRules:
    """A rules document applied to the installed mods (every relation is now between ModIds).

    ``requires`` keeps every declared requirement as its ref string (resolved or not);
    ``requires_resolved`` lists the installed mods those refs matched.
    """

    edges: tuple[PrecedenceEdge, ...] = ()
    requires: Mapping[ModId, tuple[str, ...]] = field(default_factory=dict)
    requires_resolved: Mapping[ModId, tuple[ModId, ...]] = field(default_factory=dict)
    incompatible: tuple[tuple[ModId, ModId, str], ...] = ()
    compatible: frozenset[frozenset[ModId]] = frozenset()
    tier_overrides: Mapping[ModId, str] = field(default_factory=dict)
    overlap_ignore: tuple[str, ...] = ()
    overlap_merge: tuple[str, ...] = ()

    def overlap_policy(self, path: str) -> OverlapPolicy:
        """Policy for a casefolded posix path; ``ignore`` beats ``merge`` beats ``override``."""
        normalized = path.replace("\\", "/").casefold()
        if _pattern_matcher(self.overlap_ignore)(normalized):
            return OverlapPolicy.IGNORE
        if _pattern_matcher(self.overlap_merge)(normalized):
            return OverlapPolicy.MERGE
        return OverlapPolicy.OVERRIDE

    def declares_override(self, winner: ModId, loser: ModId) -> bool:
        """Whether some declared relation says ``winner`` must beat ``loser``."""
        return any(edge.high == winner and edge.low == loser for edge in self.edges)


@dataclass(slots=True)
class _Resolver:
    """Accumulates relations while walking the rules; ``build`` freezes them."""

    mods: Mapping[ModId, ModInfo]
    matches_cache: dict[str, tuple[ModId, ...]] = field(default_factory=dict)
    edges: dict[PrecedenceEdge, None] = field(default_factory=dict)
    requires: defaultdict[ModId, list[str]] = field(default_factory=lambda: defaultdict(list))
    requires_resolved: defaultdict[ModId, list[ModId]] = field(
        default_factory=lambda: defaultdict(list)
    )
    incompatible: dict[tuple[ModId, ModId, str], None] = field(default_factory=dict)
    compatible: set[frozenset[ModId]] = field(default_factory=set)
    tier_overrides: dict[ModId, str] = field(default_factory=dict)

    def matches(self, ref: str) -> tuple[ModId, ...]:
        if ref not in self.matches_cache:
            self.matches_cache[ref] = tuple(
                mod for mod, info in self.mods.items() if match_ref(ref, info)
            )
        return self.matches_cache[ref]

    def others(self, mod: ModId, refs: tuple[str, ...]) -> list[ModId]:
        return [other for ref in refs for other in self.matches(ref) if other != mod]

    def add(self, mod: ModId, rule: ModRule) -> None:
        if rule.tier:
            self.tier_overrides[mod] = rule.tier
        self.requires[mod].extend(rule.requires)
        for dependency in self.others(mod, rule.requires):
            self.requires_resolved[mod].append(dependency)
            self.edges[PrecedenceEdge(low=dependency, high=mod, reason=EDGE_REQUIRES)] = None
        for target in self.others(mod, rule.load_after):
            self.edges[PrecedenceEdge(low=target, high=mod, reason=EDGE_LOAD_AFTER)] = None
        for target in self.others(mod, rule.patch_for):
            self.edges[PrecedenceEdge(low=target, high=mod, reason=EDGE_PATCH_FOR)] = None
        for ref, reason in rule.incompatible:
            for other in self.others(mod, (ref,)):
                self.incompatible[mod, other, reason] = None
        self.compatible.update(
            frozenset({mod, other}) for other in self.others(mod, rule.compatible_with)
        )

    def build(self, rules: RulesData) -> ResolvedRules:
        return ResolvedRules(
            edges=tuple(self.edges),
            requires={mod: tuple(dict.fromkeys(refs)) for mod, refs in self.requires.items()},
            requires_resolved={
                mod: tuple(dict.fromkeys(deps)) for mod, deps in self.requires_resolved.items()
            },
            incompatible=tuple(self.incompatible),
            compatible=frozenset(self.compatible),
            tier_overrides=dict(self.tier_overrides),
            overlap_ignore=rules.overlap_ignore,
            overlap_merge=rules.overlap_merge,
        )


def resolve_rules(rules: RulesData, mods: Mapping[ModId, ModInfo]) -> ResolvedRules:
    """Apply a rules document to the installed mods.

    Edges: ``load_after`` (the mod wins over the target), ``patch_for`` (the patch wins over its
    target) and ``requires`` (the dependent wins over its dependency).  Only relations whose
    both ends are installed become edges; self references are dropped.  When several entries
    match one mod, relations accumulate and the last ``tier`` wins.
    """
    resolver = _Resolver(mods)
    for rule in rules.mods:
        for mod in resolver.matches(rule.ref):
            resolver.add(mod, rule)
    return resolver.build(rules)
