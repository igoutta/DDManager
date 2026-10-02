"""Rule: active mods that ship the same file.

Every OVERRIDE-policy path (see ``ResolvedRules.overlap_policy``) shipped by two or more
active mods is won by the mod with the highest precedence.  Paths are grouped by their
``(winner, losers)`` outcome so a mod pair produces one finding, not one per file:

* INFO when every loser is *expected* to lose: the winner declares it overrides the loser
  (``load_after``/``patch_for``/``requires``) or the loser's tier weight is lower;
* WARNING otherwise (direction-dependent, so capped to INFO while unverified).

``details`` holds up to ``ctx.max_detail_paths`` sample paths.  Additionally a mod with at
least one OVERRIDE-policy file that wins none of them gets a "has no effect" WARNING (capped).
"""

from collections import defaultdict
from collections.abc import Mapping
from typing import Final

from src.core.ids import ModId
from src.core.rules_resolve import OverlapPolicy
from src.core.validation import Finding, Severity, ValidationContext

RULE_ID: Final = "core.file_overlap"
DESCRIPTION: Final = "Active mods that ship the same file; the higher-precedence one wins."

type Outcome = tuple[ModId, tuple[ModId, ...]]


def validate(ctx: ValidationContext) -> list[Finding]:
    owners = _override_owners(ctx)
    groups = _group_by_outcome(ctx, owners)
    findings = [
        _group_finding(ctx, winner, losers, paths) for (winner, losers), paths in groups.items()
    ]
    findings.extend(_no_effect_findings(ctx, owners))
    return findings


def _override_owners(ctx: ValidationContext) -> dict[str, list[ModId]]:
    """path -> active mods shipping it, restricted to OVERRIDE-policy paths."""
    owners: defaultdict[str, list[ModId]] = defaultdict(list)
    policy = ctx.rules.overlap_policy
    for mod, info in ctx.active_infos():
        for path in info.files:
            if policy(path) is OverlapPolicy.OVERRIDE:
                owners[path].append(mod)
    return owners


def _group_by_outcome(
    ctx: ValidationContext, owners: Mapping[str, list[ModId]]
) -> dict[Outcome, list[str]]:
    groups: defaultdict[Outcome, list[str]] = defaultdict(list)
    for path, mods in owners.items():
        if len(mods) < 2:
            continue
        ordered = ctx.by_precedence(mods)
        groups[ordered[0], ordered[1:]].append(path)
    return groups


def _expected(ctx: ValidationContext, winner: ModId, losers: tuple[ModId, ...]) -> bool:
    winner_weight = ctx.tier(winner).weight
    return all(
        ctx.rules.declares_override(winner, loser) or ctx.tier(loser).weight < winner_weight
        for loser in losers
    )


def _group_finding(
    ctx: ValidationContext, winner: ModId, losers: tuple[ModId, ...], paths: list[str]
) -> Finding:
    expected = _expected(ctx, winner, losers)
    winner_name = ctx.label(winner)
    loser_names = ", ".join(ctx.label(m) for m in losers)
    count = len(paths)
    return Finding(
        rule_id=RULE_ID,
        severity=Severity.INFO if expected else ctx.capped(Severity.WARNING),
        message=(
            f"{winner_name} overrides {count} file{'s' if count != 1 else ''} from {loser_names}"
            f"{' (expected)' if expected else ''}."
        ),
        mod_ids=(winner, *losers),
        message_key=f"finding.core.file_overlap.{'expected' if expected else 'unexpected'}",
        params=(("winner", winner_name), ("losers", loser_names), ("count", str(count))),
        details=tuple(sorted(paths)[: ctx.max_detail_paths]),
    )


def _no_effect_findings(ctx: ValidationContext, owners: Mapping[str, list[ModId]]) -> list[Finding]:
    """Active mods with OVERRIDE-policy files that lose every one of them."""
    has_files: set[ModId] = set()
    wins_some: set[ModId] = set()
    for mods in owners.values():
        has_files.update(mods)
        wins_some.add(ctx.by_precedence(mods)[0])
    return [
        _no_effect_finding(ctx, mod) for mod in ctx.order.active() if mod in has_files - wins_some
    ]


def _no_effect_finding(ctx: ValidationContext, mod: ModId) -> Finding:
    name = ctx.label(mod)
    return Finding(
        rule_id=RULE_ID,
        severity=ctx.capped(Severity.WARNING),
        message=(
            f"{name} has no effect: every file it ships is overridden by a mod that wins over it."
        ),
        mod_ids=(mod,),
        message_key="finding.core.file_overlap.no_effect",
        params=(("mod", name),),
    )
