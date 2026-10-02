"""Rule: more than one active overhaul.

Overhauls replace large parts of the game and rarely coexist.  Two active overhaul-tier mods
that are not declared ``compatible_with`` each other get one WARNING; the fix keeps the one
with the highest precedence and disables the rest.  Overhauls that are declared compatible
with every other active overhaul are left out of the finding.
"""

from typing import Final

from src.core.ids import ModId
from src.core.tiers import OVERHAUL_TIER_ID
from src.core.validation import DisableMods, Finding, Severity, ValidationContext

RULE_ID: Final = "core.multiple_overhauls"
DESCRIPTION: Final = "Several active overhaul-tier mods that are not declared compatible."


def validate(ctx: ValidationContext) -> list[Finding]:
    active = ctx.order.active()
    overhauls = ctx.by_precedence(m for m in active if ctx.tier(m).id == OVERHAUL_TIER_ID)
    conflicting = tuple(m for m in overhauls if _conflicts_with_any(ctx, m, overhauls))
    if len(conflicting) < 2:
        return []
    names = ", ".join(ctx.label(m) for m in conflicting)
    return [
        Finding(
            rule_id=RULE_ID,
            severity=Severity.WARNING,
            message=f"{len(conflicting)} overhauls are active at the same time: {names}.",
            mod_ids=conflicting,
            fix=DisableMods(conflicting[1:]),
            message_key="finding.core.multiple_overhauls",
            params=(("count", str(len(conflicting))), ("mods", names)),
        )
    ]


def _conflicts_with_any(ctx: ValidationContext, mod: ModId, overhauls: tuple[ModId, ...]) -> bool:
    compatible = ctx.rules.compatible
    return any(other != mod and frozenset({mod, other}) not in compatible for other in overhauls)
