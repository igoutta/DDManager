"""src/rules/duplicate_identity.py: (a) one SaveIdentity written twice among the active mods,
(b) local + workshop copies of the same mod (grouping)."""

from pathlib import Path

import pytest

from src.core.ids import ModId
from src.core.load_order import PriorityDirection
from src.core.validation import DisableMods, Finding, Severity
from src.rules import duplicate_identity as rule
from tests.support.factories import (
    context,
    load_order,
    local_mod,
    only,
    sample_patch_mod,
    with_severity,
    workshop_mod,
)

RULE_ID = "core.duplicate_identity"
FIRST, LAST = PriorityDirection.FIRST_WINS, PriorityDirection.LAST_WINS


def _disabled(finding: Finding) -> set[ModId]:
    assert isinstance(finding.fix, DisableMods), finding
    return set(finding.fix.mods)


def test_module_metadata() -> None:
    assert rule.RULE_ID == RULE_ID
    assert rule.DESCRIPTION.strip()


def test_distinct_identities_yield_nothing() -> None:
    mods = [
        workshop_mod("2248772895", title="The Chorus"),
        local_mod("better_stage_coach", title="Better Stage Coach"),
        local_mod("crusader_hu", title="Heroes Unchained: Crusader"),
    ]
    ctx = context(load_order(*(m.id for m in mods)), mods)
    assert rule.validate(ctx) == []


# ------------------------------------------------------------------ (a) identical SaveIdentity


@pytest.mark.parametrize("direction", [FIRST, LAST])
def test_same_identity_twice_is_an_error_keeping_the_highest_precedence_copy(
    direction: PriorityDirection,
) -> None:
    first = workshop_mod("1111111", title="SWF")
    second = workshop_mod("1111111_renamed", title="SWF copy", workshop_id="1111111")
    assert first.save_identity == second.save_identity
    ctx = context(
        load_order("1111111", "x", "1111111_renamed"),
        [first, second, local_mod("x")],
        direction=direction,
    )
    finding = only(rule.validate(ctx))
    assert finding.severity is Severity.ERROR
    assert set(finding.mod_ids) == {first.id, second.id}
    loser = second.id if direction is FIRST else first.id
    assert _disabled(finding) == {loser}


def test_three_way_identity_clash_disables_all_but_one() -> None:
    mods = [
        local_mod("a_chorus", title="The Chorus"),
        local_mod("b_chorus", title="The Chorus"),
        local_mod("c_chorus", title="The Chorus"),
    ]
    ctx = context(load_order("c_chorus", "a_chorus", "b_chorus"), mods, direction=LAST)
    finding = only(rule.validate(ctx))
    assert finding.severity is Severity.ERROR
    assert set(finding.mod_ids) == {m.id for m in mods}
    assert _disabled(finding) == {ModId("c_chorus"), ModId("a_chorus")}


def test_inactive_duplicate_does_not_count() -> None:
    mods = [local_mod("a_chorus", title="The Chorus"), local_mod("b_chorus", title="The Chorus")]
    ctx = context(load_order("a_chorus", "-b_chorus"), mods)
    assert with_severity(rule.validate(ctx), Severity.ERROR) == []


def test_identity_clash_is_not_capped_when_unverified() -> None:
    mods = [local_mod("a_chorus", title="The Chorus"), local_mod("b_chorus", title="The Chorus")]
    ctx = context(load_order("a_chorus", "b_chorus"), mods, verified=False)
    assert only(rule.validate(ctx)).severity is Severity.ERROR


# ------------------------------------------------------------------ (b) local + workshop copies


def test_real_patch_mod_installed_locally_and_from_the_workshop(sample_mods_dir: Path) -> None:
    """modding/crusader_hu_swf_compat as the local copy plus a Workshop upload with the same
    title: paired through the normalized-title key, the local copy is the one to disable."""
    local = sample_patch_mod(sample_mods_dir, "crusader_hu_swf_compat")
    uploaded = workshop_mod("3123456789", title=local.title, files=local.files)
    assert local.save_identity != uploaded.save_identity
    ctx = context(load_order("3123456789", "crusader_hu_swf_compat"), [local, uploaded])
    finding = only(rule.validate(ctx))
    assert finding.severity is Severity.WARNING
    assert set(finding.mod_ids) == {local.id, uploaded.id}
    assert _disabled(finding) == {local.id}
    assert with_severity(rule.validate(ctx), Severity.ERROR) == []


def test_local_copy_of_a_workshop_mod_is_a_warning_disabling_the_local() -> None:
    ws = workshop_mod("2248772895", title="The Chorus")
    local = local_mod("chorus_class_mod", title="The Chorus")
    ctx = context(load_order("chorus_class_mod", "2248772895"), [ws, local])
    finding = only(rule.validate(ctx))
    assert finding.severity is Severity.WARNING
    assert set(finding.mod_ids) == {ws.id, local.id}
    assert _disabled(finding) == {local.id}


def test_local_copy_matched_by_folder_name_against_the_workshop_title() -> None:
    ws = workshop_mod("2248772895", title="The Chorus")
    local = local_mod("the_chorus", title="Chorus Backup Copy")  # folder key is the title
    ctx = context(load_order("2248772895", "the_chorus"), [ws, local])
    finding = only(rule.validate(ctx))
    assert finding.severity is Severity.WARNING
    assert _disabled(finding) == {local.id}


def test_short_or_different_titles_do_not_pair() -> None:
    ws = workshop_mod("2248772895", title="Chorus")
    local = local_mod("chorus_class_mod", title="The Chorus")
    tiny_ws = workshop_mod("3333333", title="Abc")
    tiny_local = local_mod("abc", title="Abc")
    mods = [ws, local, tiny_ws, tiny_local]
    ctx = context(load_order(*(m.id for m in mods)), mods)
    assert rule.validate(ctx) == []


def test_two_workshop_copies_with_the_same_title_are_not_a_local_workshop_pair() -> None:
    mods = [
        workshop_mod("1111111", title="Same Title Here"),
        workshop_mod("2222222", title="Same Title Here"),
    ]
    ctx = context(load_order("1111111", "2222222"), mods)
    assert rule.validate(ctx) == []


def test_pair_needs_both_sides_active() -> None:
    ws = workshop_mod("2248772895", title="The Chorus")
    local = local_mod("chorus_class_mod", title="The Chorus")
    for spec in (("-chorus_class_mod", "2248772895"), ("chorus_class_mod", "-2248772895")):
        assert rule.validate(context(load_order(*spec), [ws, local])) == []


def test_pair_warning_is_not_capped_when_unverified() -> None:
    ws = workshop_mod("2248772895", title="The Chorus")
    local = local_mod("chorus_class_mod", title="The Chorus")
    ctx = context(load_order("chorus_class_mod", "2248772895"), [ws, local], verified=False)
    assert only(rule.validate(ctx)).severity is Severity.WARNING
