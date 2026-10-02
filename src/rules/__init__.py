"""Built-in health-check rules: one module per rule, adapted through ``ModuleRule``.

Imports are static on purpose: the frozen build must find every rule without scanning the
filesystem, and ``tests/test_layering.py`` keeps this package free of Qt and services.
"""

from collections.abc import Mapping
from typing import Final

from src.core.validation import ModuleRule, Rule
from src.rules import (
    declared_relations,
    duplicate_identity,
    file_overlap,
    folder_key_collision,
    missing_from_disk,
    multiple_overhauls,
    patch_before_target,
    sort_cycle,
)

BUILTIN_RULES: Final[tuple[Rule, ...]] = tuple(
    ModuleRule.from_module(module, default_prefix="core")
    for module in (
        missing_from_disk,
        duplicate_identity,
        multiple_overhauls,
        patch_before_target,
        file_overlap,
        declared_relations,
        folder_key_collision,
    )
)
"""Every rule that runs during a health check, in a stable order."""

RULE_DESCRIPTIONS: Final[Mapping[str, str]] = {
    **{rule.rule_id: rule.description for rule in BUILTIN_RULES},
    **declared_relations.SUB_RULE_DESCRIPTIONS,
    sort_cycle.RULE_ID: sort_cycle.DESCRIPTION,
}
"""Every rule id a finding may carry (including the ids that are not rules of their own)."""
