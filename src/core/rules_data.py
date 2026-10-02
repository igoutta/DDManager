"""The contract module of the community rules file: one import path for the format
(:mod:`src.core.rules_format`) and its resolution against installed mods
(:mod:`src.core.rules_resolve`)."""

from src.core.rules_format import (
    EMPTY_RULES,
    FORMAT,
    FORMAT_VERSION,
    ModRule,
    RulesData,
    canonical_ref,
    dump_rules_data,
    merge_rules,
    parse_rules_data,
)
from src.core.rules_resolve import (
    EDGE_LOAD_AFTER,
    EDGE_PATCH_FOR,
    EDGE_REQUIRES,
    OverlapPolicy,
    ResolvedRules,
    match_ref,
    resolve_rules,
)

__all__ = [
    "EDGE_LOAD_AFTER",
    "EDGE_PATCH_FOR",
    "EDGE_REQUIRES",
    "EMPTY_RULES",
    "FORMAT",
    "FORMAT_VERSION",
    "ModRule",
    "OverlapPolicy",
    "ResolvedRules",
    "RulesData",
    "canonical_ref",
    "dump_rules_data",
    "match_ref",
    "merge_rules",
    "parse_rules_data",
    "resolve_rules",
]
