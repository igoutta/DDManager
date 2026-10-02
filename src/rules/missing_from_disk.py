"""Rule: a load-order entry whose folder is not installed.

An *active* missing mod is an ERROR because it would be written into the save as an entry the
game cannot find; the fix disables it.  An *inactive* missing mod is only INFO: the legacy app
pruned such keys on every load (dd2.py:6044-6050), which wiped categories and nicknames when a
drive was briefly unmounted, so the rewrite keeps the entry and merely reports it.
"""

from typing import Final

from src.core.ids import ModId
from src.core.validation import DisableMods, Finding, Severity, ValidationContext

RULE_ID: Final = "core.missing_from_disk"
DESCRIPTION: Final = "Load-order entries whose mod folder is not on disk."


def validate(ctx: ValidationContext) -> list[Finding]:
    return [
        _active_missing(mod) if ctx.order.is_enabled(mod) else _inactive_missing(mod)
        for mod in ctx.order.entries
        if mod not in ctx.mods
    ]


def _active_missing(mod: ModId) -> Finding:
    return Finding(
        rule_id=RULE_ID,
        severity=Severity.ERROR,
        message=f"{mod} is enabled but its folder is not on disk; the game cannot load it.",
        mod_ids=(mod,),
        fix=DisableMods((mod,)),
        message_key="finding.core.missing_from_disk.active",
        params=(("mod", mod),),
    )


def _inactive_missing(mod: ModId) -> Finding:
    return Finding(
        rule_id=RULE_ID,
        severity=Severity.INFO,
        message=f"{mod} is in the load order but its folder is not on disk (it is disabled).",
        mod_ids=(mod,),
        message_key="finding.core.missing_from_disk.inactive",
        params=(("mod", mod),),
    )
