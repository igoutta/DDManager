"""Rule: relations declared in the rules file (``requires``, ``load_after``/``patch_for``,
``incompatible``) that the current load order violates.

Findings carry one of three rule ids so the UI can filter them:

* ``core.declared_requires``: an active mod requires a mod that is not installed (ERROR), or
  installed but inactive (ERROR + ``EnableMods``);
* ``core.declared_load_after``: a declared precedence edge whose high side does not win
  (WARNING, capped while the direction is unverified, + ``MakeWin``);
* ``core.declared_incompatible``: both sides of an ``incompatible`` pair are active (ERROR +
  ``DisableMods`` of the lower-precedence one).
"""

from collections.abc import Mapping
from typing import Final

from src.core.ids import ModId
from src.core.rules_resolve import match_ref
from src.core.sorting import PrecedenceEdge
from src.core.validation import (
    DisableMods,
    EnableMods,
    Finding,
    MakeWin,
    Severity,
    ValidationContext,
)

RULE_ID: Final = "core.declared_relations"
DESCRIPTION: Final = "Requirements, load-after and incompatibility rules from the rules file."

REQUIRES_ID: Final = "core.declared_requires"
REQUIRES_DESCRIPTION: Final = "A required mod is missing or disabled."
LOAD_AFTER_ID: Final = "core.declared_load_after"
LOAD_AFTER_DESCRIPTION: Final = "A declared load-after/patch-for rule is violated."
INCOMPATIBLE_ID: Final = "core.declared_incompatible"
INCOMPATIBLE_DESCRIPTION: Final = "Two mods declared incompatible are both active."

SUB_RULE_DESCRIPTIONS: Final[Mapping[str, str]] = {
    REQUIRES_ID: REQUIRES_DESCRIPTION,
    LOAD_AFTER_ID: LOAD_AFTER_DESCRIPTION,
    INCOMPATIBLE_ID: INCOMPATIBLE_DESCRIPTION,
}
"""The ids this module's findings carry, which are not rules of their own."""


def validate(ctx: ValidationContext) -> list[Finding]:
    return [
        *_missing_requirements(ctx),
        *_precedence_violations(ctx),
        *_incompatible_pairs(ctx),
    ]


# ---------------------------------------------------------------- requires


def _missing_requirements(ctx: ValidationContext) -> list[Finding]:
    findings: list[Finding] = []
    for mod in ctx.order.active():
        for ref in ctx.rules.requires.get(mod, ()):
            installed = tuple(m for m, info in ctx.mods.items() if match_ref(ref, info))
            if not installed:
                findings.append(_not_installed(ctx, mod, ref))
            elif not any(ctx.order.is_enabled(m) for m in installed):
                findings.append(_not_enabled(ctx, mod, ref, installed))
    return findings


def _not_installed(ctx: ValidationContext, mod: ModId, ref: str) -> Finding:
    name = ctx.label(mod)
    return Finding(
        rule_id=REQUIRES_ID,
        severity=Severity.ERROR,
        message=f"{name} requires {ref}, which is not installed.",
        mod_ids=(mod,),
        message_key="finding.core.declared_requires.not_installed",
        params=(("mod", name), ("ref", ref)),
    )


def _not_enabled(
    ctx: ValidationContext, mod: ModId, ref: str, installed: tuple[ModId, ...]
) -> Finding:
    name = ctx.label(mod)
    names = ", ".join(ctx.label(m) for m in installed)
    return Finding(
        rule_id=REQUIRES_ID,
        severity=Severity.ERROR,
        message=f"{name} requires {names} ({ref}), which is installed but not enabled.",
        mod_ids=(mod, *installed),
        fix=EnableMods(installed),
        message_key="finding.core.declared_requires.not_enabled",
        params=(("mod", name), ("ref", ref), ("required", names)),
    )


# ---------------------------------------------------------------- load_after / patch_for


def _precedence_violations(ctx: ValidationContext) -> list[Finding]:
    seen: set[tuple[ModId, ModId]] = set()
    findings: list[Finding] = []
    for edge in ctx.rules.edges:
        pair = (edge.high, edge.low)
        if (
            pair in seen
            or not _both_active(ctx, edge.high, edge.low)
            or ctx.wins(edge.high, edge.low)
        ):
            continue
        seen.add(pair)
        findings.append(_violation(ctx, edge))
    return findings


def _both_active(ctx: ValidationContext, a: ModId, b: ModId) -> bool:
    return ctx.order.is_enabled(a) and ctx.order.is_enabled(b)


def _violation(ctx: ValidationContext, edge: PrecedenceEdge) -> Finding:
    high_name, low_name = ctx.label(edge.high), ctx.label(edge.low)
    return Finding(
        rule_id=LOAD_AFTER_ID,
        severity=ctx.capped(Severity.WARNING),
        message=(f"{high_name} must win over {low_name} ({edge.reason} rule) but currently loses."),
        mod_ids=(edge.high, edge.low),
        fix=MakeWin(winner=edge.high, over=edge.low),
        message_key="finding.core.declared_load_after",
        params=(("winner", high_name), ("loser", low_name), ("reason", edge.reason)),
    )


# ---------------------------------------------------------------- incompatible


def _incompatible_pairs(ctx: ValidationContext) -> list[Finding]:
    seen: set[frozenset[ModId]] = set()
    findings: list[Finding] = []
    for a, b, reason in ctx.rules.incompatible:
        pair = frozenset({a, b})
        if pair in seen or not _both_active(ctx, a, b):
            continue
        seen.add(pair)
        findings.append(_incompatible(ctx, ctx.by_precedence((a, b)), reason))
    return findings


def _incompatible(ctx: ValidationContext, ordered: tuple[ModId, ...], reason: str) -> Finding:
    names = [ctx.label(m) for m in ordered]
    why = f": {reason}" if reason else ""
    return Finding(
        rule_id=INCOMPATIBLE_ID,
        severity=Severity.ERROR,
        message=f"{names[0]} and {names[1]} are declared incompatible{why}.",
        mod_ids=ordered,
        fix=DisableMods(ordered[1:]),
        message_key="finding.core.declared_incompatible",
        params=(("a", names[0]), ("b", names[1]), ("reason", reason)),
    )
