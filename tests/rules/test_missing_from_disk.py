"""src/rules/missing_from_disk.py: order entries without a ModInfo (contract: cluster C table)."""

from pathlib import Path

import pytest

from src.core.ids import ModId
from src.core.load_order import PriorityDirection
from src.core.validation import DisableMods, Severity
from src.rules import missing_from_disk as rule
from tests.support.factories import (
    context,
    load_order,
    local_mod,
    only,
    sample_patch_mod,
    with_severity,
)

RULE_ID = "core.missing_from_disk"


def test_module_metadata() -> None:
    assert rule.RULE_ID == RULE_ID
    assert rule.DESCRIPTION.strip()


def test_everything_present_yields_nothing() -> None:
    ctx = context(load_order("a", "-b", "c"), [local_mod(k) for k in ("a", "b", "c")])
    assert rule.validate(ctx) == []


def test_active_missing_mod_is_an_error_with_a_disable_fix() -> None:
    ctx = context(load_order("a", "ghost", "c"), [local_mod("a"), local_mod("c")])
    finding = only(rule.validate(ctx))
    assert finding.rule_id == RULE_ID
    assert finding.severity is Severity.ERROR
    assert finding.mod_ids == (ModId("ghost"),)
    assert finding.fix == DisableMods(mods=(ModId("ghost"),))


def test_inactive_missing_mod_is_only_informational() -> None:
    ctx = context(load_order("a", "-ghost"), [local_mod("a")])
    finding = only(rule.validate(ctx))
    assert finding.rule_id == RULE_ID
    assert finding.severity is Severity.INFO
    assert finding.mod_ids == (ModId("ghost"),)


def test_every_missing_active_mod_is_covered_by_an_error_and_a_disable_fix() -> None:
    ctx = context(load_order("g1", "a", "g2", "-g3"), [local_mod("a")])
    findings = rule.validate(ctx)
    errors = with_severity(findings, Severity.ERROR)
    assert {m for f in errors for m in f.mod_ids} == {ModId("g1"), ModId("g2")}
    fixes = [f.fix for f in errors]
    assert all(isinstance(fix, DisableMods) for fix in fixes)
    assert {m for fix in fixes if isinstance(fix, DisableMods) for m in fix.mods} == {
        ModId("g1"),
        ModId("g2"),
    }
    infos = with_severity(findings, Severity.INFO)
    assert [f.mod_ids for f in infos] == [(ModId("g3"),)]
    assert len(findings) == len(errors) + len(infos)


@pytest.mark.parametrize("direction", list(PriorityDirection))
def test_not_direction_dependent_so_never_capped(direction: PriorityDirection) -> None:
    ctx = context(load_order("ghost"), [], direction=direction, verified=False)
    assert only(rule.validate(ctx)).severity is Severity.ERROR


def test_empty_order_is_fine() -> None:
    assert rule.validate(context(load_order(), [])) == []


def test_real_patch_mod_present_while_its_target_is_gone(sample_mods_dir: Path) -> None:
    """modding/crusader_hu_swf_compat is installed; the Heroes Unchained folder it patches is
    listed but missing: only the missing folder is reported, with a disable fix."""
    patch = sample_patch_mod(sample_mods_dir, "crusader_hu_swf_compat")
    ctx = context(load_order("hu_crusader", "crusader_hu_swf_compat", "-old_ui"), [patch])
    findings = rule.validate(ctx)
    assert {f.mod_ids for f in findings} == {(ModId("hu_crusader"),), (ModId("old_ui"),)}
    error = only(with_severity(findings, Severity.ERROR))
    assert error.mod_ids == (ModId("hu_crusader"),)
    assert error.fix == DisableMods(mods=(ModId("hu_crusader"),))
    assert only(with_severity(findings, Severity.INFO)).mod_ids == (ModId("old_ui"),)
