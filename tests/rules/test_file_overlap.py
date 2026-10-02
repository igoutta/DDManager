"""src/rules/file_overlap.py: OVERRIDE-policy files shipped by several active mods, grouped by
(winner, losers), plus the "has no effect" warning for a mod that wins none of its files."""

from pathlib import Path

import pytest

from src.core.ids import ModId
from src.core.load_order import PriorityDirection
from src.core.model import ModInfo
from src.core.validation import Finding, Severity
from src.rules import file_overlap as rule
from tests.support.factories import (
    context,
    load_order,
    local_mod,
    mentions,
    only,
    rules_json,
    sample_patch_mod,
    with_severity,
)

RULE_ID = "core.file_overlap"
FIRST, LAST = PriorityDirection.FIRST_WINS, PriorityDirection.LAST_WINS
A, B, C = ModId("a"), ModId("b"), ModId("c")

CRUSADER_INFO = "heroes/crusader/crusader.info.darkest"
CRUSADER_ART = "heroes/crusader/crusader.art.darkest"


def _overlaps(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if len(f.mod_ids) >= 2]


def _no_effect(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if len(f.mod_ids) == 1]


def _groups(findings: list[Finding]) -> set[tuple[ModId, frozenset[ModId]]]:
    return {(f.mod_ids[0], frozenset(f.mod_ids[1:])) for f in _overlaps(findings)}


def test_module_metadata() -> None:
    assert rule.RULE_ID == RULE_ID
    assert rule.DESCRIPTION.strip()


def test_disjoint_manifests_yield_nothing() -> None:
    a = local_mod("a", files=("heroes/a/a.info.darkest",))
    b = local_mod("b", files=("heroes/b/b.info.darkest",))
    assert rule.validate(context(load_order("a", "b"), [a, b])) == []


def test_ignore_and_merge_policy_files_never_overlap() -> None:
    shared = ("preview_icon.png", "localization/x.string_table.xml", "heroes/old.bak")
    a = local_mod("a", files=shared)
    b = local_mod("b", files=shared)
    assert rule.validate(context(load_order("a", "b"), [a, b])) == []


@pytest.mark.parametrize("direction", [FIRST, LAST])
def test_same_tier_overlap_is_a_warning_listing_the_shared_paths(
    direction: PriorityDirection,
) -> None:
    a = local_mod("a", files=(CRUSADER_INFO, CRUSADER_ART, "heroes/a/only_a.darkest"))
    b = local_mod("b", files=(CRUSADER_INFO, CRUSADER_ART, "heroes/b/only_b.darkest"))
    ctx = context(load_order("a", "b"), [a, b], direction=direction)
    finding = only(rule.validate(ctx))
    assert finding.rule_id == RULE_ID
    assert finding.severity is Severity.WARNING
    winner, loser = (A, B) if direction is FIRST else (B, A)
    assert finding.mod_ids[0] == winner
    assert set(finding.mod_ids) == {winner, loser}
    assert finding.details == (CRUSADER_ART, CRUSADER_INFO)


def test_expected_overlap_by_tier_weight_is_informational() -> None:
    patch = local_mod("a", files=(CRUSADER_INFO,))
    base = local_mod("b", files=(CRUSADER_INFO, "heroes/b/only_b.darkest"))
    ctx = context(load_order("a", "b"), [patch, base], tiers={"a": "patch", "b": "class"})
    finding = only(rule.validate(ctx))
    assert finding.severity is Severity.INFO
    assert finding.mod_ids[0] == A


def test_lower_tier_winning_over_a_higher_tier_is_a_warning() -> None:
    base = local_mod("a", files=(CRUSADER_INFO,))
    patch = local_mod("b", files=(CRUSADER_INFO, "heroes/b/only_b.darkest"))
    ctx = context(load_order("a", "b"), [base, patch], tiers={"a": "class", "b": "patch"})
    finding = only(rule.validate(ctx))
    assert finding.severity is Severity.WARNING
    assert finding.mod_ids[0] == A


def test_declared_override_makes_the_overlap_expected() -> None:
    a = local_mod("a", files=(CRUSADER_INFO,))
    b = local_mod("b", files=(CRUSADER_INFO, "heroes/b/only_b.darkest"))
    rules = rules_json({"key:a": {"load_after": ["key:b"]}})
    ctx = context(load_order("a", "b"), [a, b], rules=rules)
    assert only(rule.validate(ctx)).severity is Severity.INFO


def test_unexpected_overlap_is_capped_to_info_while_unverified() -> None:
    a = local_mod("a", files=(CRUSADER_INFO,))
    b = local_mod("b", files=(CRUSADER_INFO, "heroes/b/only_b.darkest"))
    ctx = context(load_order("a", "b"), [a, b], verified=False)
    assert only(rule.validate(ctx)).severity is Severity.INFO


def test_details_are_sorted_and_capped_at_max_detail_paths() -> None:
    paths = tuple(f"heroes/x/file_{n:02d}.darkest" for n in (7, 3, 9, 1, 5, 2, 8))
    a = local_mod("a", files=paths)
    b = local_mod("b", files=(*paths, "heroes/b/only_b.darkest"))
    capped = only(rule.validate(context(load_order("a", "b"), [a, b], max_detail_paths=5)))
    assert capped.details == tuple(sorted(paths)[:5])
    full = only(rule.validate(context(load_order("a", "b"), [a, b], max_detail_paths=10)))
    assert full.details == tuple(sorted(paths))


def test_groups_are_keyed_by_winner_and_loser_set() -> None:
    shared_by_all = "heroes/x/all.darkest"
    shared_by_ab = "heroes/x/ab.darkest"
    a = local_mod("a", files=(shared_by_all, shared_by_ab))
    b = local_mod("b", files=(shared_by_all, shared_by_ab))
    c = local_mod("c", files=(shared_by_all,))
    findings = rule.validate(context(load_order("a", "b", "c"), [a, b, c]))
    assert _groups(findings) == {(A, frozenset({B, C})), (A, frozenset({B}))}
    by_losers = {frozenset(f.mod_ids[1:]): f.details for f in _overlaps(findings)}
    assert by_losers[frozenset({B, C})] == (shared_by_all,)
    assert by_losers[frozenset({B})] == (shared_by_ab,)


def test_inactive_mods_do_not_take_part() -> None:
    a = local_mod("a", files=(CRUSADER_INFO,))
    b = local_mod("b", files=(CRUSADER_INFO,))
    assert rule.validate(context(load_order("a", "-b"), [a, b])) == []


# ------------------------------------------------------------------ "has no effect"


def test_mod_that_wins_none_of_its_override_files_has_no_effect() -> None:
    a = local_mod("a", files=(CRUSADER_INFO, CRUSADER_ART))
    b = local_mod("b", files=(CRUSADER_INFO, CRUSADER_ART, "preview_icon.png"))
    findings = rule.validate(context(load_order("a", "b"), [a, b]))
    useless = only(_no_effect(findings))
    assert useless.rule_id == RULE_ID
    assert useless.severity is Severity.WARNING
    assert useless.mod_ids == (B,)
    assert mentions(useless, "no effect") or mentions(useless, b.title)
    assert len(_overlaps(findings)) == 1


def test_mod_with_a_unique_override_file_still_has_effect() -> None:
    a = local_mod("a", files=(CRUSADER_INFO,))
    b = local_mod("b", files=(CRUSADER_INFO, "heroes/b/only_b.darkest"))
    findings = rule.validate(context(load_order("a", "b"), [a, b]))
    assert _no_effect(findings) == []


def test_mod_with_only_ignore_or_merge_files_is_not_reported_as_useless() -> None:
    a = local_mod("a", files=("localization/x.string_table.xml",))
    b = local_mod("b", files=("localization/x.string_table.xml",))
    assert rule.validate(context(load_order("a", "b"), [a, b])) == []


def test_no_effect_follows_the_direction() -> None:
    a = local_mod("a", files=(CRUSADER_INFO,))
    b = local_mod("b", files=(CRUSADER_INFO,))
    findings = rule.validate(context(load_order("a", "b"), [a, b], direction=LAST))
    assert only(_no_effect(findings)).mod_ids == (A,)


@pytest.mark.parametrize("direction", [FIRST, LAST])
def test_no_effect_is_capped_to_info_while_unverified(direction: PriorityDirection) -> None:
    """Which mod "has no effect" depends on the direction, so the WARNING is capped like the
    overlap finding itself."""
    a = local_mod("a", files=(CRUSADER_INFO, CRUSADER_ART))
    b = local_mod("b", files=(CRUSADER_INFO, CRUSADER_ART, "preview_icon.png"))
    loser = B if direction is FIRST else A
    verified = rule.validate(context(load_order("a", "b"), [a, b], direction=direction))
    assert only(_no_effect(verified)).severity is Severity.WARNING
    assert only(_no_effect(verified)).mod_ids == (loser,)
    unverified = rule.validate(
        context(load_order("a", "b"), [a, b], direction=direction, verified=False)
    )
    useless = only(_no_effect(unverified))
    assert useless.severity is Severity.INFO
    assert useless.mod_ids == (loser,)
    assert all(f.severity is Severity.INFO for f in unverified)


# ------------------------------------------------------------------ real patch mod


def test_crusader_patch_over_its_target_is_expected(sample_mods_dir: Path) -> None:
    patch = sample_patch_mod(sample_mods_dir, "crusader_hu_swf_compat")
    hu = local_mod(
        "hu_crusader",
        title="Heroes Unchained: Crusader",
        files=(CRUSADER_INFO, "heroes/crusader/anim/attack.png"),
    )
    ctx = context(
        load_order("crusader_hu_swf_compat", "hu_crusader"),
        [patch, hu],
        tiers={"crusader_hu_swf_compat": "patch", "hu_crusader": "class"},
    )
    findings = rule.validate(ctx)
    overlap = only(_overlaps(findings))
    assert overlap.severity is Severity.INFO
    assert overlap.mod_ids == (patch.id, hu.id)
    assert overlap.details == (CRUSADER_INFO,)
    assert with_severity(findings, Severity.WARNING) == []


def test_crusader_patch_shadowed_by_its_target_is_a_warning(sample_mods_dir: Path) -> None:
    patch: ModInfo = sample_patch_mod(sample_mods_dir, "crusader_hu_swf_compat")
    hu = local_mod("hu_crusader", title="Heroes Unchained: Crusader", files=(CRUSADER_INFO,))
    ctx = context(
        load_order("hu_crusader", "crusader_hu_swf_compat"),
        [patch, hu],
        tiers={"crusader_hu_swf_compat": "patch", "hu_crusader": "class"},
    )
    overlap = only(_overlaps(rule.validate(ctx)))
    assert overlap.severity is Severity.WARNING
    assert overlap.mod_ids == (hu.id, patch.id)
