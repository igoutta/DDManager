"""Rule: two active mods that are the same mod.

Two checks:

(a) *Identical save identity*: two active mods whose ``SaveIdentity`` is the same would be
    written to ``applied_ugcs_1_0`` twice (ERROR; the fix keeps the highest-precedence copy).

(b) *Local + Workshop copies*: a local copy and a Workshop copy of one mod, detected by sharing
    a duplicate-detection key.  The grouping is a port of
    ``ModManager.detect_local_workshop_duplicates`` (dd2.py:4118-4158) restricted to active mods,
    with ``duplicate_keys`` (dd2.py:4092-4116) providing the keys; groups are deduplicated by
    their (locals, workshop) signature and sorted by the legacy sort name.  WARNING; the fix
    disables the local copies.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Final

from src.core.identity import duplicate_keys, sort_key
from src.core.ids import ModId, SaveIdentity, SourceKind
from src.core.validation import DisableMods, Finding, Severity, ValidationContext

RULE_ID: Final = "core.duplicate_identity"
DESCRIPTION: Final = (
    "Active mods that are copies of each other (same save entry, or local + Workshop)."
)


def validate(ctx: ValidationContext) -> list[Finding]:
    return [*_identical_identities(ctx), *_local_workshop_copies(ctx)]


# ---------------------------------------------------------------- (a) identical identity


def _identical_identities(ctx: ValidationContext) -> list[Finding]:
    groups: defaultdict[SaveIdentity, list[ModId]] = defaultdict(list)
    for mod, info in ctx.active_infos():
        groups[info.save_identity].append(mod)
    return [
        _identity_finding(ctx, identity, ctx.by_precedence(members))
        for identity, members in groups.items()
        if len(members) > 1
    ]


def _identity_finding(
    ctx: ValidationContext, identity: SaveIdentity, members: tuple[ModId, ...]
) -> Finding:
    names = ", ".join(ctx.label(m) for m in members)
    return Finding(
        rule_id=RULE_ID,
        severity=Severity.ERROR,
        message=(
            f"{len(members)} active mods would be written to the save as the same entry "
            f"{identity.name!r} ({identity.source}): {names}."
        ),
        mod_ids=members,
        fix=DisableMods(members[1:]),
        message_key="finding.core.duplicate_identity.identical",
        params=(("name", identity.name), ("source", identity.source), ("mods", names)),
    )


# ---------------------------------------------------------------- (b) local + workshop copies


@dataclass(frozen=True, slots=True)
class _DuplicateGroup:
    key: str
    locals: tuple[ModId, ...]
    workshop: tuple[ModId, ...]


def _index_by_key(
    ctx: ValidationContext,
) -> tuple[dict[str, list[ModId]], dict[str, list[ModId]]]:
    """dd2.py:4119-4128: bucket active mods by every duplicate-detection key, per source kind."""
    workshop_by_key: defaultdict[str, list[ModId]] = defaultdict(list)
    local_by_key: defaultdict[str, list[ModId]] = defaultdict(list)
    for mod, info in ctx.active_infos():
        target = workshop_by_key if info.kind is SourceKind.WORKSHOP else local_by_key
        for key in duplicate_keys(info):
            target[key].append(mod)
    return workshop_by_key, local_by_key


def _duplicate_groups(ctx: ValidationContext) -> list[_DuplicateGroup]:
    """dd2.py:4130-4157: pair local buckets with Workshop buckets, dedupe, sort like legacy."""
    workshop_by_key, local_by_key = _index_by_key(ctx)
    groups: list[_DuplicateGroup] = []
    seen_pairs: set[tuple[tuple[ModId, ...], tuple[ModId, ...]]] = set()
    for key, local_mods in local_by_key.items():
        workshop_mods = workshop_by_key.get(key, [])
        if not workshop_mods:
            continue
        local_unique = tuple(sorted(set(local_mods), key=str.lower))
        workshop_unique = tuple(sorted(set(workshop_mods), key=str.lower))
        signature = (local_unique, workshop_unique)
        if signature in seen_pairs:
            continue
        seen_pairs.add(signature)
        groups.append(_DuplicateGroup(key, local_unique, workshop_unique))
    groups.sort(key=lambda g: (_sort_name(ctx, g.locals[0]), _sort_name(ctx, g.workshop[0])))
    return groups


def _sort_name(ctx: ValidationContext, mod: ModId) -> str:
    """Legacy ``sort_name`` (dd2.py:3924-3928) without nicknames, which rules cannot see."""
    info = ctx.info(mod)
    return sort_key(info, None) if info is not None else str(mod).lower()


def _local_workshop_copies(ctx: ValidationContext) -> list[Finding]:
    return [_group_finding(ctx, group) for group in _duplicate_groups(ctx)]


def _group_finding(ctx: ValidationContext, group: _DuplicateGroup) -> Finding:
    local_names = ", ".join(ctx.label(m) for m in group.locals)
    workshop_names = ", ".join(ctx.label(m) for m in group.workshop)
    return Finding(
        rule_id=RULE_ID,
        severity=Severity.WARNING,
        message=(
            f"Local copy {local_names} and Workshop copy {workshop_names} look like the same mod "
            f"({group.key}); both are active."
        ),
        mod_ids=(*group.locals, *group.workshop),
        fix=DisableMods(group.locals),
        message_key="finding.core.duplicate_identity.local_workshop",
        params=(("key", group.key), ("locals", local_names), ("workshop", workshop_names)),
    )
