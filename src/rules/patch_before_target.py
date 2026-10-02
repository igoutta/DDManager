"""Rule: a patch that loses to the mod it patches.

A mod is a *patch* when its tier is ``patch``/``class_patch``, one of its tags is
``patch``/``compatibility``/``class tweaks``, or its title contains a patch-like word.
Its *targets* are, among the active mods:

* the ``patch_for`` targets declared in the rules file;
* mods named by the ``Load this after:`` bullets of its description (``load_after_hints``),
  matched by normalized-title prefix in either direction (both sides at least 5 characters);
* mods whose normalized title (at least 5 characters) appears inside the patch's title;
* mods sharing at least one OVERRIDE-policy file with the patch, unless they are patches too
  (two patches touching the same file would otherwise each be told to beat the other).

One WARNING per (patch, target) pair where the patch does not win; the fix moves the patch
right above the target.  Direction-dependent, so capped to INFO while the direction is
unverified.
"""

import re
from collections.abc import Mapping
from typing import Final

from src.core.identity_text import normalize_mod_identity
from src.core.ids import ModId
from src.core.rules_resolve import EDGE_PATCH_FOR, OverlapPolicy
from src.core.tiers import CLASS_PATCH_TIER_ID, PATCH_TIER_ID
from src.core.validation import Finding, MakeWin, Severity, ValidationContext

RULE_ID: Final = "core.patch_before_target"
DESCRIPTION: Final = "A compatibility patch that does not win over the mod it patches."

PATCH_TIERS: Final = frozenset({PATCH_TIER_ID, CLASS_PATCH_TIER_ID})
PATCH_TAGS: Final = frozenset({"patch", "compatibility", "class tweaks"})
PATCH_TITLE_RE: Final = re.compile(
    r"\b(patch|compat(ibility)?|fix(es)?|addon|add-on|tweaks?)\b", re.IGNORECASE
)
MIN_MATCH_CHARS: Final = 5


def validate(ctx: ValidationContext) -> list[Finding]:
    titles = _normalized_titles(ctx)
    patches = {m for m in titles if _is_patch(ctx, m)}
    return [
        _finding(ctx, patch, target)
        for patch in ctx.order.active()
        if patch in patches
        for target in ctx.by_precedence(_targets(ctx, patch, titles, patches))
        if not ctx.wins(patch, target)
    ]


def _is_patch(ctx: ValidationContext, mod: ModId) -> bool:
    """Tier, tag or title says this mod patches something else."""
    if ctx.tier(mod).id in PATCH_TIERS:
        return True
    info = ctx.info(mod)
    if info is None:
        return False
    if any(tag.strip().casefold() in PATCH_TAGS for tag in info.tags):
        return True
    return PATCH_TITLE_RE.search(info.title) is not None


def _normalized_titles(ctx: ValidationContext) -> dict[ModId, str]:
    return {mod: normalize_mod_identity(info.title) for mod, info in ctx.active_infos()}


def _targets(
    ctx: ValidationContext,
    patch: ModId,
    titles: Mapping[ModId, str],
    patches: set[ModId],
) -> set[ModId]:
    targets = {e.low for e in ctx.rules.edges if e.reason == EDGE_PATCH_FOR and e.high == patch}
    targets |= _hint_targets(ctx, patch, titles)
    targets |= _title_targets(patch, titles)
    targets |= _shared_file_targets(ctx, patch) - patches
    targets.discard(patch)
    return {t for t in targets if t in titles}


def _hint_targets(ctx: ValidationContext, patch: ModId, titles: Mapping[ModId, str]) -> set[ModId]:
    """``Load this after:`` bullets, matched by normalized-title prefix in either direction."""
    info = ctx.info(patch)
    if info is None:
        return set()
    hints = [
        h for h in map(normalize_mod_identity, info.load_after_hints) if len(h) >= MIN_MATCH_CHARS
    ]
    return {
        mod
        for mod, title in titles.items()
        if len(title) >= MIN_MATCH_CHARS
        and any(title.startswith(hint) or hint.startswith(title) for hint in hints)
    }


def _title_targets(patch: ModId, titles: Mapping[ModId, str]) -> set[ModId]:
    """Active mods whose normalized title appears inside the patch's title."""
    patch_title = titles.get(patch, "")
    return {
        mod
        for mod, title in titles.items()
        if mod != patch and len(title) >= MIN_MATCH_CHARS and title in patch_title
    }


def _shared_file_targets(ctx: ValidationContext, patch: ModId) -> set[ModId]:
    """Active mods that ship at least one OVERRIDE-policy file the patch also ships."""
    info = ctx.info(patch)
    if info is None:
        return set()
    overridden = {p for p in info.files if ctx.rules.overlap_policy(p) is OverlapPolicy.OVERRIDE}
    if not overridden:
        return set()
    return {
        mod
        for mod, other in ctx.active_infos()
        if mod != patch and not overridden.isdisjoint(other.files)
    }


def _finding(ctx: ValidationContext, patch: ModId, target: ModId) -> Finding:
    patch_name, target_name = ctx.label(patch), ctx.label(target)
    return Finding(
        rule_id=RULE_ID,
        severity=ctx.capped(Severity.WARNING),
        message=(
            f"{patch_name} looks like a patch for {target_name} "
            f"but {target_name} wins their conflicts."
        ),
        mod_ids=(patch, target),
        fix=MakeWin(winner=patch, over=target),
        message_key="finding.core.patch_before_target",
        params=(("patch", patch_name), ("target", target_name)),
    )
