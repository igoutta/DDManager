"""src/rules/declared_relations.py: requirements, declared precedence and incompatibilities from
the rules file (core.declared_requires / core.declared_load_after / core.declared_incompatible)."""

from pathlib import Path

import pytest

from src.core.ids import ModId
from src.core.load_order import PriorityDirection
from src.core.model import ModInfo
from src.core.validation import DisableMods, EnableMods, Finding, MakeWin, Severity
from src.rules import declared_relations as rule
from tests.support.factories import (
    context,
    load_order,
    local_mod,
    mentions,
    only,
    rules_json,
    sample_patch_mod,
    workshop_mod,
)

REQUIRES, LOAD_AFTER, INCOMPATIBLE = (
    "core.declared_requires",
    "core.declared_load_after",
    "core.declared_incompatible",
)
FIRST, LAST = PriorityDirection.FIRST_WINS, PriorityDirection.LAST_WINS

PATCH = "crusader_hu_swf_compat"
PATCH_REF = "local:crusader hu swf compatibility patch"
SWF_TITLE = "SWF (V0.25) - 2goals, QOL, mermaids, sandwiches..."


@pytest.fixture
def patch(sample_mods_dir: Path) -> ModInfo:
    return sample_patch_mod(sample_mods_dir, PATCH)


def _swf() -> ModInfo:
    return workshop_mod("1111111", title=SWF_TITLE)


def _hu() -> ModInfo:
    return local_mod("hu_crusader", title="Heroes Unchained: Crusader")


def _declared(findings: list[Finding]) -> list[Finding]:
    assert all(f.rule_id.startswith("core.declared_") for f in findings), findings
    return findings


def test_module_metadata() -> None:
    assert rule.RULE_ID.startswith("core.declared_")
    assert rule.DESCRIPTION.strip()


def test_no_rules_means_no_findings(patch: ModInfo) -> None:
    ctx = context(load_order("1111111", PATCH), [_swf(), patch])
    assert rule.validate(ctx) == []


# ------------------------------------------------------------------ requires


def test_missing_requirement_not_installed_is_an_error(patch: ModInfo) -> None:
    rules = rules_json({PATCH_REF: {"requires": ["title:superior wayfarer"]}})
    ctx = context(load_order(PATCH), [patch], rules=rules)
    finding = only(_declared(rule.validate(ctx)))
    assert finding.rule_id == REQUIRES
    assert finding.severity is Severity.ERROR
    assert finding.mod_ids == (patch.id,)
    assert finding.fix is None
    assert mentions(finding, "superior wayfarer")


def test_installed_but_inactive_requirement_offers_to_enable_it(patch: ModInfo) -> None:
    rules = rules_json({PATCH_REF: {"requires": ["steam:1111111"]}})
    ctx = context(load_order(PATCH, "-1111111"), [patch, _swf()], rules=rules)
    finding = only(_declared(rule.validate(ctx)))
    assert finding.rule_id == REQUIRES
    assert finding.severity is Severity.ERROR
    assert finding.fix == EnableMods(mods=(ModId("1111111"),))
    assert patch.id in finding.mod_ids


def test_satisfied_requirement_is_silent(patch: ModInfo) -> None:
    rules = rules_json({PATCH_REF: {"requires": ["steam:1111111", "key:hu_crusader"]}})
    ctx = context(load_order(PATCH, "1111111", "hu_crusader"), [patch, _swf(), _hu()], rules=rules)
    assert [f for f in rule.validate(ctx) if f.rule_id == REQUIRES] == []


def test_requirements_of_an_inactive_mod_are_not_checked(patch: ModInfo) -> None:
    rules = rules_json({PATCH_REF: {"requires": ["title:superior wayfarer"]}})
    ctx = context(load_order(f"-{PATCH}"), [patch], rules=rules)
    assert rule.validate(ctx) == []


def test_requirement_errors_are_not_capped(patch: ModInfo) -> None:
    rules = rules_json({PATCH_REF: {"requires": ["title:superior wayfarer"]}})
    ctx = context(load_order(PATCH), [patch], rules=rules, verified=False)
    assert only(rule.validate(ctx)).severity is Severity.ERROR


# ------------------------------------------------------------------ load_after / precedence


@pytest.mark.parametrize("direction", [FIRST, LAST])
def test_violated_load_after_is_a_warning_with_a_make_win_fix(
    patch: ModInfo, direction: PriorityDirection
) -> None:
    rules = rules_json({PATCH_REF: {"load_after": ["steam:1111111"]}})
    spec = ("1111111", PATCH) if direction is FIRST else (PATCH, "1111111")
    ctx = context(load_order(*spec), [patch, _swf()], rules=rules, direction=direction)
    finding = only(_declared(rule.validate(ctx)))
    assert finding.rule_id == LOAD_AFTER
    assert finding.severity is Severity.WARNING
    assert finding.fix == MakeWin(winner=patch.id, over=ModId("1111111"))
    assert set(finding.mod_ids) >= {patch.id, ModId("1111111")}


@pytest.mark.parametrize("direction", [FIRST, LAST])
def test_respected_load_after_is_silent(patch: ModInfo, direction: PriorityDirection) -> None:
    rules = rules_json({PATCH_REF: {"load_after": ["steam:1111111"]}})
    spec = (PATCH, "1111111") if direction is FIRST else ("1111111", PATCH)
    ctx = context(load_order(*spec), [patch, _swf()], rules=rules, direction=direction)
    assert rule.validate(ctx) == []


def test_load_after_an_inactive_or_absent_target_is_silent(patch: ModInfo) -> None:
    rules = rules_json({PATCH_REF: {"load_after": ["steam:1111111", "steam:404"]}})
    ctx = context(load_order("-1111111", PATCH), [patch, _swf()], rules=rules)
    assert rule.validate(ctx) == []


def test_patch_for_and_requires_edges_are_also_enforced(patch: ModInfo) -> None:
    rules = rules_json(
        {PATCH_REF: {"patch_for": ["key:hu_crusader"], "requires": ["steam:1111111"]}}
    )
    ctx = context(load_order("hu_crusader", "1111111", PATCH), [patch, _swf(), _hu()], rules=rules)
    findings = _declared(rule.validate(ctx))
    fixes = {f.fix for f in findings}
    assert fixes == {
        MakeWin(winner=patch.id, over=ModId("hu_crusader")),
        MakeWin(winner=patch.id, over=ModId("1111111")),
    }
    assert all(f.severity is Severity.WARNING for f in findings)


def test_precedence_warnings_are_capped_while_unverified(patch: ModInfo) -> None:
    rules = rules_json({PATCH_REF: {"load_after": ["steam:1111111"]}})
    ctx = context(load_order("1111111", PATCH), [patch, _swf()], rules=rules, verified=False)
    finding = only(rule.validate(ctx))
    assert finding.rule_id == LOAD_AFTER
    assert finding.severity is Severity.INFO
    assert finding.fix == MakeWin(winner=patch.id, over=ModId("1111111"))


# ------------------------------------------------------------------ incompatible


@pytest.mark.parametrize("direction", [FIRST, LAST])
def test_both_incompatible_mods_active_is_an_error_disabling_the_lower_one(
    patch: ModInfo, direction: PriorityDirection
) -> None:
    rules = rules_json(
        {PATCH_REF: {"incompatible": [{"ref": "key:hu_crusader", "reason": "same hero files"}]}}
    )
    ctx = context(
        load_order(PATCH, "hu_crusader"), [patch, _hu()], rules=rules, direction=direction
    )
    finding = only(_declared(rule.validate(ctx)))
    assert finding.rule_id == INCOMPATIBLE
    assert finding.severity is Severity.ERROR
    assert set(finding.mod_ids) == {patch.id, ModId("hu_crusader")}
    loser = ModId("hu_crusader") if direction is FIRST else patch.id
    assert finding.fix == DisableMods(mods=(loser,))
    assert mentions(finding, "same hero files")


def test_incompatibility_with_an_inactive_mod_is_silent(patch: ModInfo) -> None:
    rules = rules_json({PATCH_REF: {"incompatible": [{"ref": "key:hu_crusader", "reason": "x"}]}})
    ctx = context(load_order(PATCH, "-hu_crusader"), [patch, _hu()], rules=rules)
    assert rule.validate(ctx) == []


def test_incompatibility_is_reported_once_per_pair(patch: ModInfo) -> None:
    rules = rules_json(
        {
            PATCH_REF: {"incompatible": [{"ref": "key:hu_crusader", "reason": "a"}]},
            "key:hu_crusader": {"incompatible": [{"ref": PATCH_REF, "reason": "b"}]},
        }
    )
    ctx = context(load_order(PATCH, "hu_crusader"), [patch, _hu()], rules=rules)
    findings = [f for f in rule.validate(ctx) if f.rule_id == INCOMPATIBLE]
    assert {frozenset(f.mod_ids) for f in findings} == {frozenset({patch.id, ModId("hu_crusader")})}
    assert len(findings) == 1


def test_incompatibility_errors_are_not_capped(patch: ModInfo) -> None:
    rules = rules_json({PATCH_REF: {"incompatible": [{"ref": "key:hu_crusader", "reason": "x"}]}})
    ctx = context(load_order(PATCH, "hu_crusader"), [patch, _hu()], rules=rules, verified=False)
    assert only(rule.validate(ctx)).severity is Severity.ERROR


# ------------------------------------------------------------------ contract example end to end


def test_contract_example_document_against_the_real_patch(patch: ModInfo) -> None:
    rules = rules_json(
        {
            "steam:2248772895": {"title_hint": "The Chorus", "tier": "class"},
            PATCH_REF: {
                "tier": "patch",
                "requires": ["title:superior wayfarer"],
                "load_after": ["title:superior wayfarer"],
                "incompatible": [{"ref": "steam:1", "reason": "both replace heroes/crusader"}],
            },
        }
    )
    wayfarer = workshop_mod("5555555", title="Superior Wayfarer")
    foe = workshop_mod("1", title="Crusader Replacer")
    ctx = context(
        load_order("5555555", "1", PATCH), [patch, wayfarer, foe], rules=rules, direction=FIRST
    )
    findings = _declared(rule.validate(ctx))
    by_rule = {f.rule_id: f for f in findings}
    assert set(by_rule) == {LOAD_AFTER, INCOMPATIBLE}
    assert by_rule[LOAD_AFTER].fix == MakeWin(winner=patch.id, over=wayfarer.id)
    assert by_rule[INCOMPATIBLE].fix == DisableMods(mods=(patch.id,))
    assert mentions(by_rule[INCOMPATIBLE], "both replace heroes/crusader")
