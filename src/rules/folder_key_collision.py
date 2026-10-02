"""Rule: a mod folder name that exists in more than one mod root.

Discovery keeps the first root's copy and records the others in ``ModInfo.shadowed``
(first root wins, keys never change).  The shadowed copies are invisible to the load order,
so the user is told which folders are being ignored.  WARNING, no fix.
"""

from typing import Final

from src.core.ids import ModId
from src.core.model import ModInfo
from src.core.validation import Finding, Severity, ValidationContext

RULE_ID: Final = "core.folder_key_collision"
DESCRIPTION: Final = "The same mod folder name exists in several mod roots; only one is used."


def validate(ctx: ValidationContext) -> list[Finding]:
    return [_finding(mod, info) for mod, info in ctx.mods.items() if info.shadowed]


def _finding(mod: ModId, info: ModInfo) -> Finding:
    shadowed = tuple(str(path) for path in info.shadowed)
    return Finding(
        rule_id=RULE_ID,
        severity=Severity.WARNING,
        message=(
            f"{info.title or mod} ({mod}) is used from {info.path}; "
            f"{len(shadowed)} other folder{'s' if len(shadowed) != 1 else ''} with the same name "
            "are ignored."
        ),
        mod_ids=(mod,),
        message_key="finding.core.folder_key_collision",
        params=(("mod", mod), ("path", str(info.path)), ("count", str(len(shadowed)))),
        details=shadowed,
    )
